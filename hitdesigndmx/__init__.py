"""hitdesigndmx — design hitnotedmx MIDI clips and migrate Ableton lighting
clips into the current hitnotedmx note vocabulary (legacy macro-automation
now; older note mappings later)."""

from .convert import ConvertResult, convert

__all__ = ["convert", "ConvertResult"]
