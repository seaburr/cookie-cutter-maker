# Next steps (recommended)

## 1) Improve outline validation
- enforce exactly one external contour
- reject holes / multiple blobs
- add min/max area checks

## 2) Better tracing controls
Expose in UI/API:
- threshold
- simplify epsilon
- optional smoothing

## 3) STL profiles
Add selectable profiles:
- current: circle-reference topology
- sharpened cutting lip
- rounded/chamfered press edge
- different flange shapes

## 4) Caching
Hash the uploaded PNG + params -> reuse existing output.

## 5) Auth & rate limits (if you ever host)
- user auth
- quota controls
- object storage for artifacts
