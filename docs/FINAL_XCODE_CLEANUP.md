# Final Xcode cleanup

The source tree in this package has exactly these canonical folder names:

- Models
- Views
- Services
- Onboarding
- Intelligence
- DataSources

If Xcode reports that `models` refers to a disk path whose capitalization is `Models` (or the equivalent for Views/Services/Onboarding), the warning is coming from an OLD filesystem/group reference already stored in your `.xcodeproj`, not from the files in this package.

## Do this once

1. Quit Xcode.
2. Back up the `.xcodeproj` / `.xcworkspace`.
3. In the project's source directory, make sure there is only one copy of each folder, with the exact capitalization above.
4. Open Xcode.
5. In Project Navigator, remove the OLD lowercase group references (`models`, `views`, `services`, `onboarding`) using **Remove Reference** — do not move the source to Trash.
6. Add the canonical folders from this package with **Create groups** and the app target selected.
7. Search the project for `RadarHotspot`. There must be exactly one definition, in `Intelligence/HotspotEngine.swift`.
8. Search for `extension CLLocationCoordinate2D`. There must be no custom `Sendable` conformance.
9. Product -> Clean Build Folder.
10. Delete the project's DerivedData if Xcode still displays stale diagnostics, then reopen Xcode and build.

`FIX_XCODE_REFERENCES.command` can safely normalize lowercase directories on disk. It intentionally does not edit the Xcode project file because deleting arbitrary PBX file references programmatically can damage a user's existing CloudKit/signing setup.
