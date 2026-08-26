# Roach Coach Radar — Xcode cleanup for this build

This source package intentionally contains exactly these top-level source folders:

- `Models`
- `Views`
- `Services`
- `Onboarding`
- `Intelligence`
- `DataSources`

There are no lowercase duplicates and no `Phase*` folders.

## Important when replacing an existing Xcode project

Xcode stores file/group references in the `.xcodeproj` file. A ZIP cannot rewrite those references in your existing project. If Xcode still reports:

- `Models` vs `models`
- `Views` vs `views`
- `Services` vs `services`
- `Onboarding` vs `onboarding`

remove the old generated references from Project Navigator **before** adding this build. Do not add this build on top of the old references.

Recommended sequence:

1. Close Xcode.
2. Back up the project.
3. In the Project Navigator, remove the old generated `Models`, `Views`, `Services`, and `Onboarding` references (choose **Remove Reference**, not Move to Trash, if the files are also needed elsewhere).
4. Verify the project directory has only the correctly capitalized folders.
5. Add the folders from this package using **Create groups** and check Target Membership for the app target.
6. Product → Clean Build Folder.
7. Delete the project's DerivedData folder if stale diagnostics remain.
8. Build again.

## Fixes included in this build

- `RadarHotspot` has one canonical declaration in `Intelligence/HotspotEngine.swift`.
- Removed the duplicate `RadarHotspot` from `Services/RadarEngine.swift`.
- Removed the unsafe retroactive `CLLocationCoordinate2D: Sendable` conformance.
- Added `import Combine` to every source file that uses `ObservableObject` or `@Published`.
- `Sighting` is `Sendable` so it can safely participate in the async radar scan result.
- `RadarScanResult` has explicit coding keys for backend snake_case fields.
- Swift parser check passes for all Swift source files.
- Python backend compile check passes.
