import fcntl
import json
import os
import pty
import re
import select
import ssl
import struct
import subprocess
import tarfile
import termios
import urllib.request

from . import userfs

DOWNLOAD_CHUNK = 262144
PERCENT_RE = re.compile(rb"(\d{1,3})%")
# flatpak renders "Installing 2/5" and restarts its percentage for every
# operation (each runtime, then the app), so weight them into one bar.
FLATPAK_OP_RE = re.compile(rb"(?:Installing|Updating|Uninstalling)\s+(\d+)/(\d+)")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|[\r\x00-\x08\x0b-\x1f]")
COMPAT_PARTS = (".local", "share", "Steam", "compatibilitytools.d")


class Cancelled(Exception):
    pass


# Decky's loader is a PyInstaller bundle whose OpenSSL looks for CA certs at
# the build distro's paths, so the default context can come up empty here.
CA_BUNDLES = (
    "/etc/pki/tls/certs/ca-bundle.crt",
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/ssl/cert.pem",
)

_ssl_context_cache = None


def _ssl_context():
    global _ssl_context_cache
    if _ssl_context_cache is None:
        context = ssl.create_default_context()
        if not context.cert_store_stats().get("x509_ca"):
            for bundle in CA_BUNDLES:
                try:
                    context.load_verify_locations(bundle)
                    break
                except OSError:
                    continue
        _ssl_context_cache = context
    return _ssl_context_cache


def _request(url):
    return urllib.request.Request(url, headers={
        "User-Agent": "armada-store/1.0",
        "Accept": "application/vnd.github+json, application/json;q=0.9, */*;q=0.5",
    })


def _release_assets(release):
    assets = release.get("assets")
    # GitLab nests downloads as assets.links[]; GitHub and Forgejo use a flat
    # assets[] with browser_download_url.
    if isinstance(assets, dict):
        return [(link.get("name") or "", link.get("url")) for link in assets.get("links") or []]
    return [(asset.get("name") or "", asset.get("browser_download_url")) for asset in assets or []]


def resolve_release_asset(releases_url, asset_pattern):
    with urllib.request.urlopen(_request(releases_url), timeout=30, context=_ssl_context()) as resp:
        data = json.load(resp)
    releases = [data] if isinstance(data, dict) else data
    pattern = re.compile(asset_pattern)
    for release in releases:
        for name, url in _release_assets(release):
            if url and pattern.search(name):
                return release.get("tag_name") or "", url
    raise RuntimeError("No release asset matched " + asset_pattern)


def _https_only(url):
    if url.lower().startswith("https://"):
        return True
    # Escape hatch for file:// fixtures.
    return os.environ.get("ARMADA_STORE_ALLOW_INSECURE_URLS") == "1"


def download_to(fh, url, cancel, progress):
    if not _https_only(url):
        raise RuntimeError("Refusing non-HTTPS download URL")
    with urllib.request.urlopen(_request(url), timeout=60, context=_ssl_context()) as resp:
        final = resp.geturl() or url
        if not _https_only(final):
            raise RuntimeError("Refusing redirect to non-HTTPS URL")
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            if cancel.is_set():
                raise Cancelled()
            chunk = resp.read(DOWNLOAD_CHUNK)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            progress(done, total)


def _clean_output(raw):
    text = ANSI_RE.sub("\n", raw.decode("utf-8", errors="replace"))
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _run_flatpak(args, cancel, on_percent):
    # flatpak renders progress only on a sized tty with TERM set, and
    # --noninteractive suppresses it entirely; -y alone keeps this unattended.
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
    env = dict(os.environ, LC_ALL="C.UTF-8", TERM="xterm")
    proc = subprocess.Popen(["flatpak", *args], stdin=slave, stdout=slave, stderr=slave, env=env, close_fds=True)
    os.close(slave)
    output = b""
    op_index = 0
    op_total = 0
    try:
        while True:
            if cancel.is_set():
                raise Cancelled()
            ready, _, _ = select.select([master], [], [], 0.25)
            if ready:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                output = (output + chunk)[-16384:]
                ops = FLATPAK_OP_RE.findall(chunk)
                if ops:
                    op_index, op_total = int(ops[-1][0]), int(ops[-1][1])
                matches = PERCENT_RE.findall(chunk)
                if matches:
                    percent = min(100, int(matches[-1]))
                    if op_total > 1 and op_index:
                        # Equal weight per operation: sizes are unknown up front,
                        # but the result is continuous across operation changes.
                        percent = int(((op_index - 1) + percent / 100.0) / op_total * 100)
                    on_percent(max(0, min(100, percent)))
            elif proc.poll() is not None:
                break
    finally:
        os.close(master)
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        proc.wait()
    return proc.returncode, output


def install_flatpak(ref, cancel, on_percent):
    args = ["install", "--system", "--or-update", "-y", "flathub", ref]
    code, output = _run_flatpak(args, cancel, on_percent)
    if code != 0:
        message = _clean_output(output)
        if "already installed" in message:
            return
        raise RuntimeError(message or "flatpak install failed ({})".format(code))


def uninstall_flatpak(ref, cancel):
    code, output = _run_flatpak(["uninstall", "--system", "-y", ref], cancel, lambda p: None)
    if code != 0:
        message = _clean_output(output)
        if "not installed" in message:
            return
        raise RuntimeError(message or "flatpak uninstall failed ({})".format(code))


def install_appimage(install, cancel, progress):
    filename = install["filename"]
    tag = ""
    url = install.get("url")
    if not url:
        tag, url = resolve_release_asset(install["releases"], install["asset"])
    home_fd, staging_name, staging_fd = userfs.make_staging("download")
    apps_fd = None
    try:
        with userfs.create_file(staging_fd, filename, 0o755) as fh:
            download_to(fh, url, cancel, progress)
        apps_fd = userfs.open_user_path(["Applications"], create=True)
        userfs.rename(staging_fd, filename, apps_fd, filename)
    finally:
        if apps_fd is not None:
            os.close(apps_fd)
        userfs.cleanup_staging(home_fd, staging_name, staging_fd)
    return filename, tag


def remove_appimage(install, record):
    filename = install.get("filename") or (record or {}).get("filename")
    if not filename or "/" in filename:
        return
    try:
        apps_fd = userfs.open_user_path(["Applications"])
    except FileNotFoundError:
        return
    try:
        userfs.unlink(apps_fd, filename)
    finally:
        os.close(apps_fd)


# RENAME_EXCHANGE keeps the live name pointing at one complete tree even
# across a crash; the park-and-restore fallback only covers exceptions.
def _publish_compat(home_fd, staging_name, staging_fd, compat_fd, dirname, preserved):
    publish_src = "tree/" + dirname
    try:
        userfs.exchange(staging_fd, publish_src, compat_fd, dirname)
        return
    except FileNotFoundError:
        # Nothing at the live name yet: a plain rename is atomic on its own.
        os.rename(publish_src, dirname, src_dir_fd=staging_fd, dst_dir_fd=compat_fd)
        return
    except NotImplementedError:
        pass
    backed_up = False
    try:
        os.rename(dirname, "previous", src_dir_fd=compat_fd, dst_dir_fd=staging_fd)
        backed_up = True
    except FileNotFoundError:
        pass
    try:
        os.rename(publish_src, dirname, src_dir_fd=staging_fd, dst_dir_fd=compat_fd)
    except Exception as publish_error:
        restored = False
        if backed_up:
            try:
                os.rename("previous", dirname, src_dir_fd=staging_fd, dst_dir_fd=compat_fd)
                restored = True
            except OSError:
                pass
        if backed_up and not restored:
            rescue = ".armada-store-recovery-" + os.urandom(3).hex()
            try:
                os.rename(staging_name, rescue, src_dir_fd=home_fd, dst_dir_fd=home_fd)
            except OSError:
                rescue = staging_name
            userfs.grant_user_fd(staging_fd)
            preserved[0] = True
            raise RuntimeError(
                "Install failed and the previous version could not be restored; "
                "backup kept at ~/{}/previous".format(rescue)
            ) from publish_error
        raise


def install_compat(install, cancel, on_download, on_extract):
    tag, url = resolve_release_asset(install["releases"], install["asset"])
    home_fd, staging_name, staging_fd = userfs.make_staging("compat")
    compat_fd = None
    preserved_staging = [False]
    try:
        with userfs.create_file(staging_fd, "archive", 0o600) as fh:
            download_to(fh, url, cancel, on_download)
        os.mkdir("tree", dir_fd=staging_fd)
        tree_path = userfs.proc_path(staging_fd, "tree")
        with tarfile.open(userfs.proc_path(staging_fd, "archive")) as tar:
            members = tar.getmembers()
            top = {m.name.split("/", 1)[0] for m in members if m.name and not m.name.startswith((".", "/"))}
            if len(top) != 1:
                raise RuntimeError("Unexpected archive layout: " + ", ".join(sorted(top)[:4]))
            total = len(members) or 1
            for index, member in enumerate(members):
                if cancel.is_set():
                    raise Cancelled()
                tar.extract(member, tree_path, filter="data")
                if index % 100 == 0:
                    on_extract(index, total)
        dirname = top.pop()
        userfs.lchown_tree(os.path.join(tree_path, dirname))
        compat_fd = userfs.open_user_path(list(COMPAT_PARTS), create=True)
        _publish_compat(home_fd, staging_name, staging_fd, compat_fd, dirname, preserved_staging)
        return dirname, tag
    finally:
        if compat_fd is not None:
            os.close(compat_fd)
        if preserved_staging[0]:
            for fd in (staging_fd, home_fd):
                try:
                    os.close(fd)
                except OSError:
                    pass
        else:
            userfs.cleanup_staging(home_fd, staging_name, staging_fd)


def remove_compat(record):
    dirname = (record or {}).get("dir") or ""
    if not dirname or "/" in dirname or dirname in (".", ".."):
        raise RuntimeError("No recorded install directory")
    try:
        compat_fd = userfs.open_user_path(list(COMPAT_PARTS))
    except FileNotFoundError:
        return
    try:
        userfs.remove_entry(compat_fd, dirname)
    finally:
        os.close(compat_fd)
