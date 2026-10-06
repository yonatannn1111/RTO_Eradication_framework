"""Forensics package — lazy imports for snap7-dependent modules."""


def capture(*args, **kwargs):
    from .snapshot import capture as _capture
    return _capture(*args, **kwargs)


def restore(*args, **kwargs):
    from .restore import restore as _restore
    return _restore(*args, **kwargs)


def validate(*args, **kwargs):
    from .restore import validate as _validate
    return _validate(*args, **kwargs)


from .diff import diff   # safe — no external imports

__all__ = ["capture", "diff", "restore", "validate"]