"""Bounded owner-only provisioning; initial empty enrollment is setup-only."""
import json
import os
from pathlib import Path
import re
import stat


def load_provisioning(path):
    path = Path(path)
    parent = path.parent
    metadata = parent.lstat()
    if (not path.is_absolute() or parent.resolve() != parent or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_mode & 0o077 or metadata.st_uid != os.getuid()):
        raise ValueError('protected_directory_required')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        metadata = os.fstat(stream.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077 or metadata.st_nlink != 1
                or metadata.st_uid != os.getuid() or metadata.st_size > 65536):
            raise ValueError('protected_file_required')
        raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError('configuration_too_large')
        settings = json.loads(raw)
    return validate_settings(settings)


def validate_settings(settings):
    required = {'transport', 'origin', 'installation_credential', 'members'}
    if (not isinstance(settings, dict) or set(settings) not in (required, required | {'ca_file'})
            or not isinstance(settings['members'], dict) or len(settings['members']) > 1000):
        raise ValueError('configuration_invalid')
    credential = settings['installation_credential']
    if credential is None:
        if settings['members']:
            raise ValueError('configuration_invalid')
    elif not isinstance(credential, str) or not re.fullmatch(r'hi1\.[A-Za-z0-9_-]{43}', credential):
        raise ValueError('configuration_invalid')
    for subject, binding in settings['members'].items():
        if (not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', subject) or not isinstance(binding, dict)
                or set(binding) != {'link_id', 'credential'}
                or not isinstance(binding['link_id'], str)
                or not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', binding['link_id'])
                or not isinstance(binding['credential'], str)
                or not re.fullmatch(r'dg1\.[A-Za-z0-9_-]{43}', binding['credential'])):
            raise ValueError('configuration_invalid')
    return settings


def save_private_json(path, value):
    """Atomic owner-only write; never follow or overwrite an unvalidated symlink."""
    import tempfile
    path = Path(path)
    parent = path.parent
    metadata = parent.lstat()
    if (not path.is_absolute() or parent.resolve() != parent or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_mode & 0o077 or metadata.st_uid != os.getuid()):
        raise ValueError('protected_directory_required')
    if path.exists() or path.is_symlink():
        load_private_json(path)
    raw = json.dumps(value).encode()
    if len(raw) > 65536:
        raise ValueError('configuration_too_large')
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=parent, delete=False) as stream:
            name = stream.name
            os.chmod(name, 0o600)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def load_private_json(path):
    # Reuse the file boundary without imposing the provisioning schema.
    path = Path(path)
    parent = path.parent
    metadata = parent.lstat()
    if (not path.is_absolute() or parent.resolve() != parent or not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_mode & 0o077 or metadata.st_uid != os.getuid()):
        raise ValueError('protected_directory_required')
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor, 'rb') as stream:
        metadata = os.fstat(stream.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077 or metadata.st_nlink != 1
                or metadata.st_uid != os.getuid() or metadata.st_size > 65536):
            raise ValueError('protected_file_required')
        value = json.loads(stream.read(65537))
    if not isinstance(value, dict):
        raise ValueError('configuration_invalid')
    return value
