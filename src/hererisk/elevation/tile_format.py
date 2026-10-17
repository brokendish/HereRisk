"""GSI elevation PNG tile format constants (demtile spec: 256x256, 24-bit RGB).

Dependency-free so that read-side code (lookup / validate core / public API)
can use them without importing the Download operation.
"""

TILE_WIDTH = 256
TILE_HEIGHT = 256
TILE_BIT_DEPTH = 8
TILE_COLOR_TYPE = 2  # truecolour RGB
