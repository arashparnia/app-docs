# Gap 4: What "captured" promises, and the durability state machine (local-durable → off-device-durable → destination-verified)

Research date: 2026-11-03. Scope: the exact promise behind the haptic "captured", the three-tier durability state machine and its timing on Wi-Fi/LTE under a 30-page-per-minute queue, the Data Protection class that lets a background upload daemon read the queue after lock while keeping the archive encrypted, iCloud Backup exclusion and SQLite sync settings, which off-device copy is mandatory on Apple devices (iCloud Drive container vs CloudKit `CKAsset` vs service escrow bucket), the failure scenarios (force-quit, 48 h airplane mode, app deletion, device loss) and the pre-ship test matrix.

Method note: the shared web-search budget for this run was exhausted before this dimension started, so every fact below comes from direct fetches of primary pages (Apple developer-doc JSON endpoints, Apple Support, SQLite.org, Apple DevForums posts by Apple DTS, GRDB docs) rather than search. Two numbers I could not source this way (US LTE median upload speed; F_FULLFSYNC latency on iPhone NAND) are marked **unknown** with a planning assumption.

## 1. Executive summary

1. "Captured" must mean exactly one thing in code and UI: **S1 local-durable** = the corrected page blob is written with `F_FULLFSYNC` + atomic rename and the ledger row is committed in SQLite WAL with `synchronous=FULL` and `fullfsync=ON`. This is achievable in well under a second and is durable across app crash, force-quit, reboot and 48 h of airplane mode. It is **not** durable against app deletion or device loss.
2. The honest second tier, **S2 off-device-durable** ("Safe", lock icon), is network-bound and system-scheduled; no Apple mechanism makes it sub-second, and the only way to make it near-instant is a service bucket written from the foreground, which v1 does not have. The UI must show S1 and S2 as two distinct states; the paper-disposal advice is "when the lock shows".
3. Recommended mandatory first off-device copy for v1 (no backend): the **iCloud Drive ubiquity container (`Documents/`, visible in Files)**, because the OS "initiates and manages" the upload independently of the app process, the data survives app deletion, it is user-owned and Files-visible, and ADP users get end-to-end encryption for free. CloudKit `CKAsset` duplicates iCloud quota use and is invisible to the user; keep CloudKit for the small ledger mirror only.
4. Any enabled destination (Drive, Synology, iCloud Drive) that verifies first satisfies S2; full-iCloud users (5 GB free tier) fall through to their other destinations automatically. The service-owned R2 escrow is a service-phase, opt-in "relay" with a TTL, not a v1 requirement.
5. Data Protection: everything a system daemon or background task must touch (ledger, outbox, staging blobs, ubiquity files) is **Class C**; Class A is applied by lifecycle (vault blobs after they are replicated, the OCR/entity content DB that is only opened in the foreground), with background enrichment results staged in Class B files that are merged on next unlock.
6. Keep pending blobs and the ledger **inside iCloud Backup**; exclude a blob from backup only once it is destination-verified (Apple's guidance: exclude what the user can re-download, never what they cannot recreate).
7. Force-quit cancels all background `URLSession` tasks and blocks relaunch until the user opens the app; the app must reconcile `getAllTasks()` against the outbox on every launch. Enqueue uploads while in the foreground (non-discretionary, no resume-rate-limiter delay) and batch them.
8. A 30-page/minute burst produces ~36 MB/min (~4.8 Mbit/s) if the first off-device artifact is a ~1.2 MB corrected JPEG, or ~9 MB/min (~1.2 Mbit/s) if it is the ~300 KB archival PDF/A page; Wi-Fi keeps up, LTE may lag by minutes. Upload the compact artifact first.
9. The pre-ship test matrix has 24 device-only cases (Section 4.6); the three that most often fail in the wild are lock-within-5-seconds-of-capture, force-quit-then-relaunch reconciliation, and iCloud-quota-full fallback.
10. Biggest residual risk: the ~1–10 minute window between S1 and S2 on LTE, where app deletion or device destruction loses pages; it is the price of "no backend" and must be stated in the product's durability doc.

## 2. Findings

### 2.1 Background transfers: what survives what (Apple's own words)

| Fact | Source |
|---|---|
| A background session "hands control of the transfers over to the system, which handles the transfers in a separate process. In iOS, this configuration makes it possible for transfers to continue even when the app itself is suspended or terminated." | [background(withIdentifier:)](https://developer.apple.com/documentation/foundation/urlsessionconfiguration/background(withidentifier:)) |
| "If the user terminates the app from the multitasking screen, the system cancels all of the session's background transfers. In addition, the system does not automatically relaunch apps that were force quit by the user. The user must explicitly relaunch the app before transfers can begin again." | same |
| "In iOS 8 and later the background session persists but all of the tasks are cancelled." Use `NSURLErrorBackgroundTaskCancelledReasonKey` to see why. | [Quinn, Testing Background Session Code](https://developer.apple.com/forums/thread/14855) |
| Force quit sets "a flag that prevents the app from being launched in the background. That flag gets cleared when the user next launches the app manually… there's no documented way for your app to override the user's choice." | [Quinn, iOS Background Execution Limits](https://developer.apple.com/forums/thread/685525) |
| `waitsForConnectivity` "is ignored by background sessions, which always wait for connectivity." | [waitsForConnectivity](https://developer.apple.com/documentation/foundation/urlsessionconfiguration/waitsforconnectivity) |
| `timeoutIntervalForResource` "default value is 7 days." | [timeoutIntervalForResource](https://developer.apple.com/documentation/foundation/urlsessionconfiguration/timeoutintervalforresource) |
| `isDiscretionary` "applies only to transfers that your app starts while it is in the foreground. For transfers started while your app is in the background, the system always starts transfers at its discretion." Default false. | [isDiscretionary](https://developer.apple.com/documentation/foundation/urlsessionconfiguration/isdiscretionary) |
| Resume rate limiter: `nsurlsessiond` "maintains a delay value for your app. It doubles that delay every time it resumes (or relaunches) your app"; resets to 0 when the user brings the app to the front or when the delay elapses without a resume; "when your app creates a new task while it is in the background, the task does not start until that delay has expired"; mitigate by starting tasks in batches and using "fewer, larger transfers". (Historical post; Apple says it is now covered in "Downloading files in the background".) | [Quinn, resume rate limiter](https://developer.apple.com/forums/thread/14854) |
| `sessionSendsLaunchEvents` (default true): the system "automatically wakes up or launches the iOS app in the background when the session's tasks finish or require authentication" and calls `application(_:handleEventsForBackgroundURLSession:completionHandler:)`. | [sessionSendsLaunchEvents](https://developer.apple.com/documentation/foundation/urlsessionconfiguration/sessionsendslaunchevents) |
| Background sessions support upload and download tasks only; uploads go through `uploadTask(with:fromFile:)`. | [URLSession](https://developer.apple.com/documentation/foundation/urlsession), [uploadTask(with:fromFile:)](https://developer.apple.com/documentation/foundation/urlsession/uploadtask(with:fromfile:)) |
| iOS 26 `BGContinuedProcessingTask`: starts in the foreground, "needs to run the task only in response to someone's action", shows progress in a Live Activity, "can also use the network", and "The system can terminate a continuous background task abruptly… under resource constraints… prioritizes the termination of tasks that reflect minimal or no progress." | [Performing long-running tasks](https://developer.apple.com/documentation/backgroundtasks/performing-long-running-tasks-on-ios-and-ipados), [BGContinuedProcessingTask](https://developer.apple.com/documentation/backgroundtasks/bgcontinuedprocessingtask) |
| `BGProcessingTask` launch delay "can be many hours"; debug with `_simulateLaunchForTaskWithIdentifier:` / `_simulateExpirationForTaskWithIdentifier:` (devices only, never ship). | [Starting and Terminating Tasks During Development](https://developer.apple.com/documentation/backgroundtasks/starting-and-terminating-tasks-during-development) |
| Testing rules: "Test on a real device, not in Simulator. Run your app from the Home screen rather than running it from Xcode. Don't use force quit to test the 'relaunch in the background case'"; simulate system termination by calling `exit` (test builds only); deleting the app "removes… everything created by the app, including any background sessions." | [Quinn, Testing Background Session Code](https://developer.apple.com/forums/thread/14855) |

Consequence: a background `URLSession` is a good *transport* for user-owned REST destinations, but it is only "off-device" once the server has acknowledged; until then a force-quit or app deletion loses the in-flight transfer (the local blob survives force-quit, not deletion).

### 2.2 Data Protection classes vs. zero-interaction background work

| Class | Apple's definition (quoted) | Usable by background upload daemon after lock? |
|---|---|---|
| A `complete` | "accessible only when the device is unlocked"; class key discarded "about 10 seconds after lock" when Require Passcode is Immediately | No. `isProtectedDataAvailable == false` means "files that were assigned the complete or completeUnlessOpen protection key cannot be read or written by your app." |
| B `completeUnlessOpen` | "can be created while the device is locked, but once closed, cannot be opened again until the device is unlocked. If the file is opened when unlocked, you may continue to access the file normally, even if the user locks the device." | Only for a file handle already open at lock time. A daemon or a retry that re-opens the file after lock fails. Good for *writing* results while locked. |
| C `completeUntilFirstUserAuthentication` | "(Default) The file is inaccessible until the first time the user unlocks the device. After the first unlocking… the file remains accessible until the device shuts down or reboots." | Yes. Still AES-encrypted at rest; protects a powered-off or rebooted stolen device (BFU), not an unlocked-once-then-locked device (AFU). |
| D `none` | always accessible | Never. |

Sources: [Apple Platform Security, Data Protection classes](https://support.apple.com/guide/security/data-protection-classes-secb010e978a/web), [Encrypting Your App's Files](https://developer.apple.com/documentation/uikit/encrypting-your-app-s-files), [completeUnlessOpen](https://developer.apple.com/documentation/foundation/fileprotectiontype/completeunlessopen), [isProtectedDataAvailable](https://developer.apple.com/documentation/uikit/uiapplication/isprotecteddataavailable).

Apple's own guidance for exactly this pattern: "If your app supports background capabilities… assign a different protection level for files that you might access while in the background. For example, a fitness app might use the complete unless open protection level on a file that it uses to log location events in the background", while "Files containing personal information about the user, or files created directly by the user, always warrant the strongest level of protection" ([Encrypting Your App's Files](https://developer.apple.com/documentation/uikit/encrypting-your-app-s-files)). SQLite specifically: GRDB documents that "When a database is protected, an application that runs in the background on a locked device won't be able to read or write from it. Instead, it will catch DatabaseError with code SQLITE_IOERR (10) 'disk I/O error', or SQLITE_AUTH (23) 'not authorized'" ([GRDB DatabaseConnections](https://raw.githubusercontent.com/groue/GRDB.swift/master/GRDB/Documentation.docc/DatabaseConnections.md)).

Keychain parallel: `kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly` "is recommended for items that need to be accessed by background applications"; `kSecAttrAccessibleWhenPasscodeSetThisDeviceOnly` "is recommended for items that only need to be accessible while the application is in the foreground" and "Disabling the device passcode causes all items in this class to be deleted" ([AfterFirstUnlockThisDeviceOnly](https://developer.apple.com/documentation/security/ksecattraccessibleafterfirstunlockthisdeviceonly), [WhenPasscodeSetThisDeviceOnly](https://developer.apple.com/documentation/security/ksecattraccessiblewhenpasscodesetthisdeviceonly)). Note the last sentence: storing the *only* copy of a vault key under WhenPasscodeSet means "user turns off passcode = archive unreadable". Storage OAuth tokens and any vault key used by the uploader must be AfterFirstUnlock.

I could not find an Apple page that states in so many words that `nsurlsessiond` fails on a Class A source file; the conclusion follows from the class semantics (the daemon runs in a separate process and may need to re-open the file after a connectivity change, hours after lock). Treat it as a required test (Section 4.6, T4), not an assumption.

### 2.3 Durable local write: fsync, F_FULLFSYNC, WAL, atomic rename

- Apple's `fsync(2)`: "while fsync() will flush all data from the host to the drive… the drive itself may not physically write the data to the platters for quite some time and it may be written in an out-of-order sequence… This is not a theoretical edge case… For applications that require tighter guarantees about the integrity of their data, Mac OS X provides the F_FULLFSYNC fcntl." ([fsync(2) man page](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/fsync.2.html)).
- SQLite: `PRAGMA fullfsync` "determines whether or not the F_FULLFSYNC syncing method is used on systems that support it. The default value of the fullfsync flag is off. Only Mac OS X supports F_FULLFSYNC." If set, `checkpoint_fullfsync` is irrelevant because all syncs use it ([pragma.html](https://www.sqlite.org/pragma.html)).
- `synchronous`: "FULL is atomic, consistent, isolated, and durable (ACID) in WAL mode"; "WAL mode is always consistent with synchronous=NORMAL, but WAL mode does lose durability. A transaction committed in WAL mode with synchronous=NORMAL might roll back following a power loss or system crash. Transactions are durable across application crashes regardless of the synchronous setting or journal mode." "EXTRA is no different from FULL in WAL mode." ([pragma.html](https://www.sqlite.org/pragma.html), [wal.html](https://www.sqlite.org/wal.html)).
- "SQLite in WAL mode is far more forgiving of out-of-order writes… A sync failure during a COMMIT might result in loss of durability but not in a corrupt database file." ([howtocorrupt.html](https://www.sqlite.org/howtocorrupt.html)).
- `Data.write(.atomic)` "write[s] data to an auxiliary file first and then replace[s] the original file with the auxiliary file when the write completes" ([NSData.WritingOptions.atomic](https://developer.apple.com/documentation/foundation/nsdata/writingoptions/atomic)); it does not promise F_FULLFSYNC, so the blob path must be: write temp file in the vault directory → `fcntl(fd, F_FULLFSYNC)` → `rename` → commit ledger row. Cost of F_FULLFSYNC on iPhone NAND: **unknown** (no public measurement found); plan for 5–50 ms and measure with signposts (T1).

Practical reading: an app crash never loses a committed row even with NORMAL; only an OS crash or sudden power loss (dead battery mid-write) can. Because "captured" is the moment the user discards paper, pay for FULL + fullfsync on the *ops* database (ledger/outbox; one small transaction per page) and keep NORMAL on the large content/FTS database.

### 2.4 iCloud Backup: what is included, what to exclude

- Apple: "iCloud Backup includes app data for the apps that you've downloaded on your device… If the app uses iCloud Drive to store data, that information is stored in iCloud instead of your iCloud Backup." Backups of a device with Backup turned off "are kept for 180 days before being deleted." ([What iCloud Backup includes](https://support.apple.com/en-us/HT207428), published May 1 2025).
- `/tmp` and `/Library/Caches` are purged by the system and excluded from backup by default; "Don't use these directories to exclude nonpurgeable data from iCloud Backup." For non-purgeable data: "if your app allows the user to import arbitrary files such as PDFs… don't exclude those files because it might be difficult, even impossible, for the user to re-create them on a restored device." `isExcludedFromBackup` "exists only to provide guidance to the system… it's not a mechanism to guarantee those items never appear in a backup", and "certain file operations can reset resource values, make sure you set an excluded file's resource values each time you save it." ([Optimizing Your App's Data for iCloud Backup](https://developer.apple.com/documentation/foundation/optimizing-your-app-s-data-for-icloud-backup), [isExcludedFromBackupKey](https://developer.apple.com/documentation/foundation/urlresourcekey/isexcludedfrombackupkey)).
- Under standard protection, "the keys to your backups are secured in Apple data centers"; with Advanced Data Protection, iCloud Backup, iCloud Drive and "CloudKit encrypted fields and assets are end-to-end encrypted" ([iCloud data security overview](https://support.apple.com/en-us/102651)).

Answer to the gap question: the local store and SQLite should **not** be blanket-excluded. Pending (S1-only) blobs are user-created data the user cannot recreate; they belong in backup as a free secondary net. Exclude a blob only after it reaches S3 (replicated) and re-apply the flag on every rewrite.

### 2.5 Candidate first off-device copies on Apple devices

| Candidate | Who moves the bytes | Survives force-quit | Survives app deletion | Counts against user iCloud quota | User-visible / user-owned | E2EE | Commit signal | Source |
|---|---|---|---|---|---|---|---|---|
| iCloud Drive ubiquity container (`Documents/`) | The OS: "your app does not communicate directly with iCloud servers. Instead, the operating system initiates and manages uploading and downloading" | Expected yes (OS-managed; Apple does not state force-quit explicitly; **test T9**) | Yes, files remain in the user's iCloud Drive and are deletable in Files/Settings (Apple support lists "Delete folders or files in iCloud Drive" as the way to reclaim space) | Yes; failure code `ubiquitousFileNotUploadedDueToQuota`; "If you run out of iCloud storage… iCloud Drive and other iCloud apps won't stay up to date" | Yes (Files app) | Only with ADP | `ubiquitousItemIsUploadedKey` via `NSMetadataQuery` ("don't poll this key from within a block that you pass to coordinate(readingItemAt:…)"); no server hash | [iCloud Design Guide](https://developer.apple.com/library/archive/documentation/General/Conceptual/iCloudDesignGuide/Chapters/iCloudFundametals.html), [ubiquitousItemIsUploadedKey](https://developer.apple.com/documentation/foundation/urlresourcekey/ubiquitousitemisuploadedkey), [ubiquitousFileNotUploadedDueToQuota](https://developer.apple.com/documentation/foundation/cocoaerror/code/ubiquitousfilenotuploadedduetoquota), [Manage iCloud storage](https://support.apple.com/en-us/HT204247) |
| CloudKit `CKAsset`, private DB | CloudKit; `isLongLived` operations "continue to run after the user closes your app" and are recoverable via `fetchAllLongLivedOperationIDs` | Documented for "closes your app"; force-quit **unknown** (test T10) | Yes (private DB persists) | Yes: "Data in the private database counts toward the user's iCloud storage quota"; `CKError.quotaExceeded`: "Prompt the user to go to iCloud settings" | No (opaque to Files; "Data in the private database isn't visible in the developer portal") | Yes by default: "CloudKit encrypts CKAsset by default… ultimately encrypts the asset data to a key in the user's iCloud Keychain"; iCloud Keychain reset = data "permanently lost" (`zoneNotFound` + `CKErrorUserDidResetEncryptedDataKey`) | Operation completion; each `CKAsset` "supports up to 50GB assuming the user has enough remaining iCloud Storage" (Apple engineer, May 2026) | [privateCloudDatabase](https://developer.apple.com/documentation/cloudkit/ckcontainer/privateclouddatabase), [quotaExceeded](https://developer.apple.com/documentation/cloudkit/ckerror/code/quotaexceeded), [Encrypting User Data](https://developer.apple.com/documentation/cloudkit/encrypting-user-data), [longLivedOperation(for:)](https://developer.apple.com/documentation/cloudkit/ckcontainer/longlivedoperation(for:)), [forum 827897](https://developer.apple.com/forums/thread/827897) |
| Service-owned E2EE R2 bucket | App, foreground `URLSession` (sub-second for a 300 KB object on Wi-Fi) then background session | No for in-flight; yes once acked | Yes | No | No (service-owned) | App-level envelope encryption | Server 200 + `x-amz-checksum-sha256` match | storage.md (R2 $0.015/GB-month, egress free) |
| User's Google Drive / Synology via background `URLSession` | `nsurlsessiond` | No (tasks cancelled until relaunch) | No for in-flight; yes once acked | No | Yes | No | Drive `sha256Checksum`; Synology MD5 job | storage.md |

iCloud economics: 5 GB free; iCloud+ 50 GB $0.99, 200 GB $2.99, 2 TB $9.99, 6 TB $29.99, 12 TB $59.99 per month (US) ([iCloud+ plans](https://support.apple.com/en-us/108047), page dated Sep 16 2026). What fraction of Apple accounts sit at a full 5 GB is **unknown** (Apple publishes no figure); the product must assume it is common.

CKSyncEngine timing claim (vendor, WWDC23): "In normal conditions, sync will be pretty fast, usually within a few seconds or so. However, if there's no network connection, or if the device's battery is low, then sync might be delayed or deferred"; the scheduler "monitors system conditions like network connectivity, battery level, resource usage" ([WWDC23 10188](https://developer.apple.com/videos/play/wwdc2023/10188/)). The session never mentions assets; the equivalent number for iCloud Drive file uploads is **unknown** and must be measured (T11).

### 2.6 Throughput budget for a 30-page/minute burst

Assumptions (flagged): corrected 300-dpi JPEG of a letter page ≈ 1.0–1.5 MB (apple.md estimates 6–10 MB for 48 MP raw stills); archival PDF/A page with JPEG/MRC ≈ 150–400 KB (output.md). US LTE median upload speed: **unknown from a primary source in this run** (Ookla and Opensignal pages were not fetchable); planning assumptions 5 Mbit/s typical, 1 Mbit/s poor cell, 20+ Mbit/s home Wi-Fi.

| First off-device artifact | Bytes/min at 30 ppm | Needed bitrate | Wi-Fi 20 Mbit/s | LTE 5 Mbit/s | LTE 1 Mbit/s |
|---|---|---|---|---|---|
| Corrected JPEG (1.2 MB) | 36 MB | 4.8 Mbit/s | keeps up (~1 s lag/page) | borderline; backlog ≈ 0 after session | backlog grows 27 MB/min; 10-min session drains in ~36 min |
| Archival PDF/A page (300 KB) | 9 MB | 1.2 Mbit/s | keeps up | keeps up | backlog grows 1.9 MB/min; drains in ~2 min |
| Raw 48 MP still (8 MB) | 240 MB | 32 Mbit/s | lags | hopeless during the session | hopeless |

So the first off-device copy must be the compact artifact that still satisfies "print-ready": the perspective-corrected, enhanced page image (or the PDF/A page as soon as the on-device pipeline produces it, ~1 s later per architecture.md). Raw stills stay local-only as a cache and never gate S2. The per-page S1 cost (write 1–2 MB + two F_FULLFSYNC'd commits) is far below the 2 s per-page cadence.

## 3. Options compared: what "captured" means and where the first copy lives

| Option | S1→"captured" latency | S2 latency (Wi-Fi / LTE) | Works when iCloud is full | Survives force-quit | Survives app deletion | Survives device loss | Honest with "user-owned, no backend" | Verdict |
|---|---|---|---|---|---|---|---|---|
| A. "Captured" = atomic local write only (architecture.md, capture.md) | <100 ms | n/a | yes | yes | no | no | yes | Necessary but insufficient; must be labelled S1 |
| B. Local + CloudKit `CKAsset` (apple.md) | <100 ms | few s / tens of s (vendor claim) | **no** | likely (long-lived ops; untested on force-quit) | yes | yes | half: Apple-hosted, not Files-visible, double quota with iCloud Drive | Reject as asset hop; keep for ledger |
| C. Local + iCloud Drive container, other destinations as peers | <100 ms | unknown, system-scheduled; measure | **no**, but falls through to Drive/NAS | expected yes (OS daemon) | yes | yes | yes (Files-visible, user's account) | **Recommend for v1** |
| D. Local + service escrow bucket first (storage.md) | <100 ms | ~1 s / 2–5 s per 300 KB page from foreground | yes | partial (in-flight lost; re-sent on launch) | yes | yes | no (service storage; needs backend + E2EE key management) | Service phase, opt-in relay with TTL |
| E. "Captured" only after S2 (haptic waits for network) | 1–30 s | same as C/D | depends | n/a | yes | yes | yes | Offer as "shred-safe" toggle, not default: breaks the speed promise and the 30 ppm cadence |

## 4. Recommendation for this project

### 4.1 Vocabulary and state machine (per page, per destination)

```
S0 framed        (in memory)              no promise, no haptic
S1 captured      local-durable            haptic + solid card; blob F_FULLFSYNC'd + renamed, ledger row committed (WAL, synchronous=FULL, fullfsync=ON)
S2 safe          off-device-durable       lock icon; >=1 destination row in `verified` (server hash match, or iCloud isUploaded==true + size match)
S3 replicated    destination-verified     every enabled destination `verified`; local blob demoted to cache, isExcludedFromBackup=true, protection promoted to Class A
```
Per-destination outbox row: `pending → staged(file, class C) → uploading(task_id/session_uri, bytes) → uploaded(remote_id, etag) → verified(hash_match_at) | failed(reason, retry_at) | needs_attention(auth/quota)`. S2 is the OR over destinations; S3 the AND. The capture screen shows only the S1 card and the S2 lock; counts live on a status screen. Paper-disposal copy: "Captured" means it is safely on this phone; the lock means it is also in your iCloud Drive / Google Drive / NAS.

### 4.2 Timing targets and what is honest to claim

- S1: p95 < 150 ms after the still is corrected (budget: encode 20–60 ms, F_FULLFSYNC blob unknown/5–50 ms, two fsync'd SQLite commits). This supports the "sub-second captured" claim.
- S2 on Wi-Fi with iCloud Drive or Drive/R2: target p50 < 5 s, p95 < 60 s for a 300 KB artifact; measure, do not promise. On LTE at 30 ppm the lock may lag minutes; the UI shows "17 safe · 13 uploading" rather than pretending.
- Never claim "sub-second durable". Claim "sub-second captured; safe within seconds on Wi-Fi".

### 4.3 Data Protection choice (resolves privacy.md Class A vs apple.md Class C)

| Store | Class | Why |
|---|---|---|
| Ops DB (ledger, hashes, outbox, resumable URIs), WAL + synchronous=FULL + fullfsync=ON | C | Written on capture, read by background upload reconciliation and BGTasks after lock; a protected SQLite returns SQLITE_IOERR/SQLITE_AUTH when locked (GRDB) |
| Staging blobs in the outbox (corrected JPEG / PDF-A page) | C, `isExcludedFromBackup=false` while pending | `nsurlsessiond` and the iCloud daemon must open them after lock; deleted at S3 |
| Files in the iCloud Drive ubiquity container | default (C) | OS daemon reads them |
| Vault blobs after S3 | A (promote via `fileProtectionKey`) | No background process needs them any more; exports/printing are foreground |
| Content DB (OCR text, entities, summaries, FTS index) | A, opened only in foreground | Most sensitive derived data; Apple: user data files "always warrant the strongest level of protection" |
| Background enrichment results (Claude JSON, OCR text) produced while locked | B files, one per page, merged into the Content DB at `applicationProtectedDataDidBecomeAvailable` | Class B "can be created while the device is locked, but once closed, cannot be opened again until the device is unlocked" — exactly the write-only-while-locked pattern |
| Vault key / OAuth tokens / Anthropic key | Keychain `AfterFirstUnlockThisDeviceOnly` for anything the uploader needs; `WhenPasscodeSetThisDeviceOnly` only for the Content DB key | AfterFirstUnlock is Apple's recommendation "for items that need to be accessed by background applications"; WhenPasscodeSet items are deleted if the user disables the passcode |

Export-control note from privacy.md stands: using only OS Data Protection (no SQLCipher/CryptoKit on content) keeps the OS-only exemption. If the founder wants AFU-state protection for pending blobs, the only option is app-level envelope encryption with the key in Secure Enclave-backed Keychain, which does not help against a jailbroken AFU device either; document the limitation instead.

### 4.4 Mandatory first off-device copy

v1 (personal, no backend): **iCloud Drive ubiquity container is the default first hop**, written as `<Container>/Documents/<Year>/<doc-id>/page-N.pdf` (one PDF/A page per file, as output.md leans) via `NSFileCoordinator`, with `NSMetadataQuery` driving `uploaded → verified` on `ubiquitousItemIsUploadedKey == true` plus size match (iCloud Drive exposes no hash; add a sidecar `.sha256` file as a self-check). On `ubiquitousFileNotUploadedDueToQuota`, `ubiquityIdentityToken == nil` or a signed-out account, the engine does not stall: S2 is satisfied by whichever other enabled destination verifies first (Drive via `sha256Checksum`, Synology via MD5 job, NAS/WebDAV via HEAD size + sampled re-read, per storage.md). If no destination is reachable, the capture screen stays usable and a single amber state "On this phone only · 23 pages" persists until resolved.

Do not use CloudKit `CKAsset` for page bytes in v1: it spends the same iCloud quota a second time, is invisible in Files, ties durability to iCloud Keychain (a keychain reset makes data "permanently lost"), and its sync engine does not document asset scheduling. Use CloudKit later for the small encrypted ledger mirror (multi-device), where `CKSyncEngine`'s "within a few seconds" fits.

Service phase: add an opt-in **relay** (R2, app-level E2EE, 30-day TTL, deleted once the user's destinations verify) explicitly for users whose iCloud is full and whose NAS is off; it is the only way to make S2 near-instant and independent of the user's storage health, but it is a feature the user turns on, not the definition of "captured".

### 4.5 Scenario outcomes under the recommendation

| Scenario | S1 pages | In-flight S2 | Recovery action |
|---|---|---|---|
| App crash / jetsam | kept (durable across app crashes regardless of sync mode) | background `URLSession` continues in `nsurlsessiond`; app relaunched for events | On launch: recreate session, `getAllTasks()`, diff vs outbox, re-enqueue |
| Force-quit mid-upload | kept | all `URLSession` tasks cancelled, no relaunch until user opens app; iCloud Drive daemon expected to continue (T9); CloudKit long-lived op continues (force-quit untested, T10); `BGContinuedProcessingTask` ends | Same reconciliation; show "Open the app to finish saving N pages" local notification if pending > 0 after 30 min (notification scheduling is allowed from the foreground before quit) |
| 48 h airplane mode | kept | background sessions "always wait for connectivity"; resource timeout default 7 days (set 30 days); iCloud daemon waits | Nothing lost; S2 lag is visible; after 24 h pending, local notification |
| Device storage full | S1 cannot complete | n/a | Never fake it: pre-check `volumeAvailableCapacityForImportantUsage`, refuse capture with a visible reason |
| iCloud quota full | kept | iCloud rows `needs_attention(quota)`; other destinations proceed | Banner once; deep link to iCloud settings; relay (service phase) |
| App deleted | **lost** with the container and its background sessions; also lost: iCloud Backup copy if backup is stale | iCloud Drive files and CloudKit data persist in the user's account | On reinstall, rebuild the ledger from iCloud Drive (sidecars) — idempotent by sha256 |
| Device lost/destroyed | lost unless in the last iCloud Backup snapshot (periodic; frequency not under app control) | S2 pages safe; under ADP end-to-end encrypted | New device: restore backup, then reconcile against destinations |
| Reboot before first unlock | kept (Class C unavailable until first unlock, then fine) | daemon work resumes after first unlock | none |
| iCloud Keychain reset (CloudKit path only) | n/a | CloudKit encrypted data "permanently lost" | Reason not to put bytes in CloudKit |
| Restore from iCloud Backup on new device | ledger + pending blobs restored (because not excluded) | outbox rows re-enqueued | Hash-idempotent uploads prevent duplicates |

### 4.6 Pre-ship test matrix (device only; run from Home screen; use `exit()` not force-quit to simulate system termination)

| # | Test | Pass criterion |
|---|---|---|
| T1 | 200-page S1 latency with os_signpost, iPhone 13 and current model | p95 < 150 ms; F_FULLFSYNC cost recorded |
| T2 | Kill -9 / crash injection between blob rename and ledger commit, 100 iterations | Orphan blobs reconciled on launch; no row without blob |
| T3 | WAL durability: `synchronous=FULL` + `fullfsync` vs NORMAL under `exit()` 100× | Zero missing rows in both; document that power-loss durability is untestable on iPhone and rely on FULL |
| T4 | Capture, lock within 5 s, leave locked 10 min on Wi-Fi | All outbox files Class C readable; uploads complete while locked |
| T5 | Same as T4 with a deliberately Class A staging file | Upload fails — proves the class matters and the detection path works |
| T6 | Force-quit mid-batch, relaunch after 1 h | Cancelled tasks carry `NSURLErrorBackgroundTaskCancelledReasonKey`; reconciliation re-enqueues; no duplicates at destination |
| T7 | Airplane mode 48 h (real time), then Wi-Fi | All pending reach S2; no resource timeouts (set 30 days) |
| T8 | Airplane mode past the resource timeout (set 1 h for the test) | Task fails, outbox retries with backoff, nothing lost |
| T9 | iCloud Drive: write 50 files, force-quit immediately, watch iCloud.com from a Mac | Files appear without relaunch (confirms OS-daemon behavior) |
| T10 | CloudKit long-lived `CKModifyRecordsOperation` with a 20 MB asset, force-quit at 10% | Document result (unknown today); decides whether CloudKit is ever an asset hop |
| T11 | iCloud Drive S2 latency, 300 KB files, Wi-Fi vs LTE profile, 100 samples | p50/p95 recorded; used in the product copy |
| T12 | iCloud account at 5 GB full (test account) | `ubiquitousFileNotUploadedDueToQuota` surfaced once; fallback destination verifies; no stall |
| T13 | iCloud signed out / `ubiquityIdentityToken == nil` | Engine falls through; capture unaffected |
| T14 | Delete app with 20 pending pages, reinstall | Ledger rebuilt from iCloud Drive sidecars; pending-only pages reported as lost in a clear list (this is the known hole) |
| T15 | Restore iCloud Backup to a second device with pending pages | Pending blobs present, uploads resume, no duplicates (hash idempotency) |
| T16 | ADP on vs off | No behavior change; document E2EE difference |
| T17 | Network Link Conditioner "3G"/1 Mbit/s profile, 30 ppm for 10 min | UI shows accurate safe/uploading counts; backlog drains; no OOM |
| T18 | Background resume-rate limiter: 500 single tasks created in background vs batched in foreground | Batched/foreground path shows no doubling delays |
| T19 | `BGContinuedProcessingTask` on iOS 26: leave capture screen with 100 pending; lock | Live Activity progress; system termination handled; uploads continue via `URLSession` anyway |
| T20 | Low storage (fill disk to <200 MB) | Capture refused with reason; no half-written blobs |
| T21 | Destination-side deletion (delete a verified file in Drive/iCloud Drive from another device) | Nightly `BGProcessingTask` reconciliation re-uploads or flags; S3 state reverts |
| T22 | Corruption injection: flip a byte in a staged blob before upload | Hash mismatch detected by Drive `sha256Checksum` / S3 `BadDigest`; page re-staged from vault |
| T23 | Passcode disabled by user | `WhenPasscodeSet` items gone; uploader keys (`AfterFirstUnlock`) intact; Content DB re-keyed with warning |
| T24 | Class B staging merge: enrichment runs while locked, unlock later | B files merged into Class A Content DB; search finds the text within 1 s of unlock |

## 5. Risks and unknowns

- **iCloud Drive upload timing and force-quit behavior are undocumented.** Apple only says the OS "initiates and manages" transfers; T9/T11 decide whether the lock icon is seconds or minutes away.
- **Full iCloud accounts are common and Apple publishes no share.** The fallback-to-other-destination rule is mandatory, and a v1 user with only iCloud configured and a full account has no S2 at all.
- **No primary source for US LTE upload speed in this run** (search budget exhausted; Ookla/Opensignal pages blocked). The 1/5/20 Mbit/s planning tiers are assumptions.
- **F_FULLFSYNC latency on iPhone is unmeasured**; if it is tens of ms, batching two commits per page is still fine, but do not add more fsync points.
- **Class C is the ceiling for anything touched in the background.** AFU-state extraction of pending blobs is a documented limitation, not a bug.
- **`isExcludedFromBackup` is advisory** and resets on some file operations; backup contents must never be relied on as the S2 copy.
- **Force-quit is a hard hole for `URLSession` and `BGContinuedProcessingTask`**; only OS-managed stores (iCloud Drive, possibly CloudKit long-lived ops) survive it.
- **The 50 GB per-`CKAsset` and "within a few seconds" CloudKit figures are vendor/forum claims**, not measurements.
- **The `BGContinuedProcessingTask` cancel-on-force-quit statement in apple.md is not in Apple's doc text** fetched here; Apple only says the system may terminate it abruptly under resource constraints.
- **Stale-source flag:** Quinn's rate-limiter post (iOS 8 era) says the behavior is now in Apple's "Downloading files in the background" article, which I could not fetch this run; re-verify the doubling rule against the current article.

## 6. Open questions for the founder

1. Is the default haptic allowed to fire at S1 (captured on phone) with the lock icon following, or must the app withhold the haptic until S2 ("shred-safe" mode) at the cost of speed on LTE?
2. May v1 require at least one non-iCloud destination (Google Drive or NAS) to be configured before the app allows scanning, so that full-iCloud users still get S2?
3. One PDF/A per page or per document in the iCloud Drive folder? Per page makes S2 granular and idempotent; per document delays the lock until the last page.
4. Is the service-phase relay (R2, E2EE, 30-day TTL) acceptable as an opt-in, or is service storage ruled out even as a transient?
5. Which iOS minimum: the Class B staging merge and background `URLSession` work on iOS 17; `BGContinuedProcessingTask` needs iOS 26.
6. Should the app send a local notification when pages have been S1-only for more than N hours (zero interaction, but a nudge)?
7. For multi-device later, is CloudKit (encrypted fields, iCloud Keychain-bound) acceptable for the ledger mirror given "keychain reset = ledger lost" (bytes would still be in iCloud Drive)?

## 7. Sources

- Apple, URLSessionConfiguration.background(withIdentifier:): https://developer.apple.com/documentation/foundation/urlsessionconfiguration/background(withidentifier:)
- Apple, waitsForConnectivity: https://developer.apple.com/documentation/foundation/urlsessionconfiguration/waitsforconnectivity
- Apple, timeoutIntervalForResource: https://developer.apple.com/documentation/foundation/urlsessionconfiguration/timeoutintervalforresource
- Apple, isDiscretionary: https://developer.apple.com/documentation/foundation/urlsessionconfiguration/isdiscretionary
- Apple, sessionSendsLaunchEvents: https://developer.apple.com/documentation/foundation/urlsessionconfiguration/sessionsendslaunchevents
- Apple, URLSession overview: https://developer.apple.com/documentation/foundation/urlsession
- Apple, uploadTask(with:fromFile:): https://developer.apple.com/documentation/foundation/urlsession/uploadtask(with:fromfile:)
- Apple, NSURLErrorBackgroundTaskCancelledReasonKey: https://developer.apple.com/documentation/foundation/nsurlerrorbackgroundtaskcancelledreasonkey
- Apple DTS (Quinn), Testing Background Session Code: https://developer.apple.com/forums/thread/14855
- Apple DTS (Quinn), iOS Background Execution Limits: https://developer.apple.com/forums/thread/685525
- Apple DTS (Quinn), URLSession resume rate limiter: https://developer.apple.com/forums/thread/14854
- Apple, Performing long-running tasks on iOS and iPadOS (BGContinuedProcessingTask): https://developer.apple.com/documentation/backgroundtasks/performing-long-running-tasks-on-ios-and-ipados
- Apple, BGContinuedProcessingTask: https://developer.apple.com/documentation/backgroundtasks/bgcontinuedprocessingtask
- Apple, BGContinuedProcessingTaskRequest: https://developer.apple.com/documentation/backgroundtasks/bgcontinuedprocessingtaskrequest
- Apple, Starting and Terminating Tasks During Development: https://developer.apple.com/documentation/backgroundtasks/starting-and-terminating-tasks-during-development
- Apple Platform Security, Data Protection classes: https://support.apple.com/guide/security/data-protection-classes-secb010e978a/web
- Apple, Encrypting Your App's Files: https://developer.apple.com/documentation/uikit/encrypting-your-app-s-files
- Apple, FileProtectionType.completeUnlessOpen: https://developer.apple.com/documentation/foundation/fileprotectiontype/completeunlessopen
- Apple, UIApplication.isProtectedDataAvailable: https://developer.apple.com/documentation/uikit/uiapplication/isprotecteddataavailable
- Apple, kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly: https://developer.apple.com/documentation/security/ksecattraccessibleafterfirstunlockthisdeviceonly
- Apple, kSecAttrAccessibleWhenPasscodeSetThisDeviceOnly: https://developer.apple.com/documentation/security/ksecattraccessiblewhenpasscodesetthisdeviceonly
- GRDB, Database Connections (data protection and SQLITE_IOERR/SQLITE_AUTH): https://raw.githubusercontent.com/groue/GRDB.swift/master/GRDB/Documentation.docc/DatabaseConnections.md
- Apple, fsync(2) man page (F_FULLFSYNC): https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/fsync.2.html
- SQLite, PRAGMA statements (fullfsync, checkpoint_fullfsync, synchronous): https://www.sqlite.org/pragma.html
- SQLite, Write-Ahead Logging: https://www.sqlite.org/wal.html
- SQLite, How To Corrupt An SQLite Database File: https://www.sqlite.org/howtocorrupt.html
- Apple, NSData.WritingOptions.atomic: https://developer.apple.com/documentation/foundation/nsdata/writingoptions/atomic
- Apple, Optimizing Your App's Data for iCloud Backup: https://developer.apple.com/documentation/foundation/optimizing-your-app-s-data-for-icloud-backup
- Apple, isExcludedFromBackupKey: https://developer.apple.com/documentation/foundation/urlresourcekey/isexcludedfrombackupkey
- Apple Support, What iCloud Backup includes: https://support.apple.com/en-us/HT207428
- Apple Support, iCloud data security overview (ADP): https://support.apple.com/en-us/102651
- Apple Support, iCloud+ plans and pricing: https://support.apple.com/en-us/108047
- Apple Support, Manage your iCloud storage (5 GB free; what stops when full): https://support.apple.com/en-us/HT204247
- Apple Support, Delete apps on your iPhone or iPad: https://support.apple.com/en-us/HT207618
- Apple, iCloud Design Guide (archived), iCloud Fundamentals: https://developer.apple.com/library/archive/documentation/General/Conceptual/iCloudDesignGuide/Chapters/iCloudFundametals.html
- Apple, FileManager.url(forUbiquityContainerIdentifier:): https://developer.apple.com/documentation/foundation/filemanager/url(forubiquitycontaineridentifier:)
- Apple, FileManager.ubiquityIdentityToken: https://developer.apple.com/documentation/foundation/filemanager/ubiquityidentitytoken
- Apple, ubiquitousItemIsUploadedKey: https://developer.apple.com/documentation/foundation/urlresourcekey/ubiquitousitemisuploadedkey
- Apple, ubiquitousItemIsUploadingKey: https://developer.apple.com/documentation/foundation/urlresourcekey/ubiquitousitemisuploadingkey
- Apple, ubiquitousItemUploadingErrorKey: https://developer.apple.com/documentation/foundation/urlresourcekey/ubiquitousitemuploadingerrorkey
- Apple, CocoaError.Code.ubiquitousFileNotUploadedDueToQuota: https://developer.apple.com/documentation/foundation/cocoaerror/code/ubiquitousfilenotuploadedduetoquota
- Apple, FileManager.evictUbiquitousItem(at:): https://developer.apple.com/documentation/foundation/filemanager/evictubiquitousitem(at:)
- Apple, CKContainer.privateCloudDatabase (quota statement): https://developer.apple.com/documentation/cloudkit/ckcontainer/privateclouddatabase
- Apple, CKError.Code.quotaExceeded: https://developer.apple.com/documentation/cloudkit/ckerror/code/quotaexceeded
- Apple, CKAsset: https://developer.apple.com/documentation/cloudkit/ckasset
- Apple, CKAsset.init(fileURL:): https://developer.apple.com/documentation/cloudkit/ckasset/init(fileurl:)
- Apple, Encrypting User Data (CloudKit): https://developer.apple.com/documentation/cloudkit/encrypting-user-data
- Apple, CKOperation.Configuration.isLongLived: https://developer.apple.com/documentation/cloudkit/ckoperation/configuration-swift.class/islonglived
- Apple, CKContainer.longLivedOperation(for:): https://developer.apple.com/documentation/cloudkit/ckcontainer/longlivedoperation(for:)
- Apple, CKContainer.fetchAllLongLivedOperationIDs: https://developer.apple.com/documentation/cloudkit/ckcontainer/fetchalllonglivedoperationids(completionhandler:)
- Apple DevForums, CKAsset size limit (Apple Frameworks Engineer, May 2026): https://developer.apple.com/forums/thread/827897
- Apple, WWDC23 session 10188, Sync to iCloud with CKSyncEngine: https://developer.apple.com/videos/play/wwdc2023/10188/
- Prior reports in this research set: architecture.md, capture.md, storage.md, privacy.md, apple.md, output.md (same directory)
