# Durable delivery to user-owned storage (iCloud Drive, Google Drive, Synology, others)

Research date: 2026-11-03. Dimension: where the canonical copy lives, how an iOS app gets documents durably into user-chosen storage with multi-destination fan-out, and which sync engine (if any) to build on. Web-search budget ran out near the end; the final few items (Dropbox production rules, Ditto, PowerSync pricing) were confirmed by direct fetch of vendor pages, and anything I could not confirm is marked "unknown" or "flag".

## 1. Executive summary

- Make the phone the source of truth for the *ledger* (SQLite + WAL), not for the bytes: "safe to shred" should mean "SHA-256-verified in at least one remote destination", never "written to the app sandbox". Apple cancels every background transfer and will not relaunch the app if the user force-quits it, so an on-device-only copy is not a guarantee ([Apple](https://developer.apple.com/documentation/foundation/urlsessionconfiguration/background(withidentifier:))).
- Fan-out is a per-(document, destination) outbox table with persisted resumable-upload state (Drive session URI, Graph uploadUrl, Dropbox session_id, S3 UploadId). All four major targets expose resumable protocols with 1-week session lifetimes.
- Google Drive: use only `drive.file` (non-sensitive, basic verification). `drive`/`drive.readonly` are restricted scopes needing an annual CASA security assessment and ~6 weeks review ([Google](https://developers.google.com/workspace/drive/api/guides/api-specific-auth), [FAQ](https://support.google.com/cloud/answer/13463817)). Drive returns `sha256Checksum` on every binary file, which gives free post-upload verification.
- iCloud Drive: use the ubiquity container's `Documents/` folder (visible in Files), `NSFileCoordinator` + `NSMetadataQuery`, and treat `ubiquitousItemIsUploadedKey == true` as the commit signal. CloudKit `CKAsset` is a worse fit for user-browsable PDFs (data is opaque to Files/Finder) but is useful for the ledger.
- Synology: there is no official Synology Drive SDK. Ship WebDAV (HTTPS, port 5006) as the primary NAS path, File Station Web API (`SYNO.FileStation.Upload`, multipart, `create_parents`) as the second, and treat QuickConnect as unusable for third-party apps. Reachability (Tailscale / reverse proxy + Let's Encrypt) is the user's problem; TLS pinning UX is ours.
- Do not adopt PowerSync/Electric/Replicache/Ditto for the file pipeline. They sync rows, not multi-megabyte PDFs into third-party folders. The right shape is an rclone-style connector layer in Swift plus a small home-grown outbox. PowerSync's Swift SDK is the only viable candidate if you later want a hosted multi-device ledger, and its attachment helper is still alpha on Swift.
- For the multi-tenant service, own an encrypted R2/S3 "escrow" bucket as the first commit target (egress free on R2, $0.015/GB-month), then mirror to user-owned storage. This is the only way to make "captured" mean "durable" within ~1 s regardless of the user's Drive/NAS state.

## 2. Findings

### 2a. iCloud Drive (ubiquity container, UIDocument/NSFileCoordinator, CloudKit)

| Fact | Value | Source |
|---|---|---|
| Making the app folder visible in Files | Add `NSUbiquitousContainers` to Info.plist with `NSUbiquitousContainerIsDocumentScopePublic=true`, `NSUbiquitousContainerName`, `NSUbiquitousContainerSupportedFolderLevels=ANY`; bump `CFBundleVersion` every time the entry changes; the `Documents` folder must exist and hold at least one file | [Apple sample (iOS 14+)](https://developer.apple.com/documentation/uikit/synchronizing-documents-in-the-icloud-environment) |
| Discovery | Use `NSMetadataQuery` with `NSMetadataQueryUbiquitousDataScope`/`DocumentsScope`; file-system APIs are not reliable because iOS does not download data until asked | same |
| Coordination | All reads/writes must go through `NSFileCoordinator` (UIDocument does this for you) | same |
| Upload-complete signal | `URLResourceKey.ubiquitousItemIsUploadedKey` (read-only Bool). Apple warns: do not poll it inside a coordinated-read block; observe via `NSMetadataQuery` or `NSFilePresenter` | [Apple](https://developer.apple.com/documentation/foundation/urlresourcekey/ubiquitousitemisuploadedkey) |
| Conflicts | `ubiquitousItemHasUnresolvedConflictsKey`; resolve with `NSFileVersion.unresolvedConflictVersionsOfItem(at:)` then `removeOtherVersionsOfItem`; UIDocument posts `stateChangedNotification` | [Apple](https://developer.apple.com/documentation/foundation/urlresourcekey/ubiquitousitemhasunresolvedconflictskey), sample above |
| Per-file size cap | 50 GB per file, quoted from Apple's iCloud Drive FAQ by Apple Community posts; I could not retrieve the current Apple page (HT201104 and 118308 no longer state it) — **flag** | [Apple Community](https://discussions.apple.com/thread/6603001?page=1) |
| Background upload behaviour | System-managed by the cloud daemon, no latency SLA; first upload sends the whole file, later changes send deltas (old Apple design guide) | [Apple archive](https://developer.apple.com/library/archive/documentation/General/Conceptual/iCloudDesignGuide/Chapters/DesigningForDocumentsIniCloud.html) |
| Extended attributes | Finder tags (`com.apple.metadata:_kMDItemUserTags`) sync through iCloud Drive; other `kMDItem*` xattrs are not preserved unless the name carries the `#S` syncable flag (independent testing on macOS 26.4.1, May 2026) | [Eclectic Light](https://eclecticlight.co/2026/05/12/what-gets-synced-in-icloud-drive/) |
| Spotlight | `CSSearchableItemAttributeSet.contentURL` lets Spotlight de-duplicate your items against iCloud Drive items; Core Spotlight indexing is app-centric, so index from your own ledger, not from the Files copy | [Apple](https://developer.apple.com/documentation/corespotlight/cssearchableitemattributeset/contenturl), [forum](https://developer.apple.com/forums/thread/805925) |
| CloudKit `CKAsset` | Apple Frameworks Engineer: each `CKAsset` may be up to 50 GB subject to the user's remaining quota; handle `CKError.quotaExceeded`. The CKAsset page itself states no limit. Private-database data counts against the user's iCloud storage | [Apple forum](https://developer.apple.com/forums/thread/827897), [CKAsset](https://developer.apple.com/documentation/cloudkit/ckasset) |
| `CKSyncEngine` | iOS 17+, automates batching, retries, push, account changes; app persists state serialization and resolves `serverRecordChanged` conflicts itself — from training knowledge, Apple page not fetchable (**flag: verify**) | — |

Implication: the iCloud Drive path is "write a new immutable file into `Documents/<vault>/YYYY/...pdf` via a coordinated write, then wait for `ubiquitousItemIsUploaded`". Because we never rewrite a file, iCloud conflicts cannot arise for the PDFs; they can only arise for the sidecar/index files, which is why the ledger should not be a single JSON file in iCloud (use CloudKit records or per-document sidecars instead).

### 2b. Google Drive API v3

| Topic | Fact | Source |
|---|---|---|
| Scopes | `drive.file` = non-sensitive (basic verification only); `drive.appdata` non-sensitive; `drive`, `drive.readonly`, `drive.metadata(.readonly)` = restricted (restricted-scope verification + annual security assessment if data is stored/transmitted on servers; limited to backup/sync, productivity, reporting apps) | [Google](https://developers.google.com/workspace/drive/api/guides/api-specific-auth) |
| Verification timelines | Brand verification ~2–3 business days; sensitive ~10 business days; restricted ~6 weeks; unverified apps with sensitive/restricted scopes capped at 100 new users for the project's lifetime; CASA assessment paid to assessor, repeated annually | [Google FAQ](https://support.google.com/cloud/answer/13463817) |
| Brand verification needs | Homepage on an owned, Search-Console-verified domain; privacy policy on the same domain linked from the consent screen; Google branding guidelines | [Google](https://support.google.com/cloud/answer/13464321) |
| Upload types | simple/multipart ≤5 MB; resumable for >5 MB or flaky networks; chunks must be multiples of 256 KB except the last; session URI expires after one week; status check = empty `PUT` with `Content-Range: bytes */size` → 308 + `Range` header, 404 = restart | [Google](https://developers.google.com/workspace/drive/api/guides/manage-uploads) |
| Limits | 750 GB/user/day uploads; 5 TB max file; project quota 1,000,000 units/min, 325,000 units/min/user; read 5 units, list 100, edit 50, download 200; 403 "User rate limit exceeded"/429 → exponential backoff | [Google](https://developers.google.com/workspace/drive/api/guides/limits) |
| Custom properties | `appProperties` (private to app) and `properties` (public); max 100 per file, 30 private per app, 30 public, **124 bytes key+value UTF-8**; searchable with `appProperties has { key='x' and value='y' }` | [Google](https://developers.google.com/workspace/drive/api/guides/properties), [search](https://developers.google.com/workspace/drive/api/guides/search-files) |
| Checksums | `md5Checksum`, `sha1Checksum`, `sha256Checksum` are output-only fields on binary files; nothing to send on upload, compare after | [Google files resource](https://developers.google.com/workspace/drive/api/reference/rest/v3/files) |
| Folder semantics | Names are not unique in a folder; a file has exactly one parent; `contentHints.indexableText` ≤128 KB improves `fullText` | same |
| Full-text search | `fullText contains` matches name, description, indexableText and content on whole tokens; phrase search with double quotes | [Google](https://developers.google.com/workspace/drive/api/guides/ref-search-terms) |
| Indexing limits | Drive extracts only the first 1 MB of text per file; PDF OCR limited to 80 pages; PDFs over 50 MB or 80 pages are not indexed (stated as Drive's own index limits in a Google Cloud doc) — **flag**: consumer-Drive help page not retrieved | [Google Cloud](https://docs.cloud.google.com/gemini/enterprise/docs/connectors/gdrive) |

Implications: with `drive.file` the app can only see files it created, so the "Documents vault" folder must be created by the app and remembered by ID (names are not unique, so never look folders up by name alone). Searching the user's whole Drive is out of scope (and would push you into restricted scopes). The 124-byte property limit means `appProperties` can carry a document ID and a truncated SHA-256, not tags; tags go in the sidecar and `indexableText`.

### 2c. Synology NAS from a mobile app

| Path | What I found | Source |
|---|---|---|
| File Station Web API | Official guide (DSM 6-era PDF, still the only official doc). Login: `GET /webapi/auth.cgi?api=SYNO.API.Auth&version=3&method=login&account=&passwd=&session=FileStation&format=sid`; sid expires after 7 days by default; `otp_code` param exists but the guide says "WebAPI doesn't support it yet". Upload: `SYNO.FileStation.Upload` v2, RFC 1867 multipart, params `path`, `create_parents`, `overwrite` (v2 true/false; v3 `overwrite`/`skip`; error if omitted and file exists), `mtime`/`crtime`/`atime` in ms, file part must be last. `SYNO.FileStation.MD5` is a non-blocking start/status/stop task (DSM 6.0+). `SYNO.FileStation.CreateFolder` exists | [Synology PDF](https://global.download.synology.com/download/Document/Software/DeveloperGuide/Package/FileStation/All/enu/Synology_File_Station_API_Guide.pdf) |
| DSM 7 specifics | Only community, reverse-engineered references exist (pmilano1 repo: `SYNO.API.Auth` v6 login example; explicitly "not endorsed by Synology"). The Python `synology-drive-api` wrapper logs in with DSM creds plus `otp_code`, supports `dsm_version='7'`, `conflict_action` `version`/`autorename`, auto-creates parents; it does not use QuickConnect | [pmilano1](https://github.com/pmilano1/synology-dsm-api), [zbjdonald](https://github.com/zbjdonald/synology-drive-api) |
| Synology Drive API | `SYNO.SynologyDrive.*` is undocumented; forum users could not even get authenticated requests working reliably. No official SDK | [Synology forum](https://community.synology.com/enu/forum/1/post/149809) |
| WebDAV Server package | Not installed by default; HTTP 5005 / HTTPS 5006 (changeable); Synology says use HTTPS on iOS 12+; remote use needs port forwarding or VPN | [Synology KB](https://kb.synology.com/th-th/DSM/help/WebDAVServer/webdav_server?version=7), [tutorial](https://www.synology.com/hu-hu/knowledgebase/tutorials/610) |
| SMB via Files app | iOS 13+ Files can mount SMB; a third-party app can obtain a folder via `UIDocumentPickerViewController` and persist a bookmark; Apple warns network volumes can disappear and all I/O must be off the main thread; DTS gave conflicting guidance on security-scoped bookmarks on iOS — **flag**. No background-upload story at all (the app process must be alive to write) | [Apple](https://developer.apple.com/documentation/uikit/providing-access-to-directories), [forum](https://developer.apple.com/forums/thread/773373) |
| QuickConnect | Only carries Synology's own apps; relays through Synology servers when NAT traversal fails and the relay is slow (community consensus, no official statement found) | [WunderTech](https://www.wundertech.net/synology-nas-remote-access/) |
| Tailscale | Official package; Package Center copy is outdated, install the SPK manually; DSM 7 needs a boot-time `tailscale configure-host` task to get a TUN; `--accept-routes` unsupported; firewall rule for 100.64.0.0/10 | [Tailscale KB](https://tailscale.com/kb/1131/synology) |
| Embedding Tailscale in our app | TailscaleKit (libtailscale, BSD-3) builds iOS frameworks, routes `URLSession` via `URLSessionConfiguration.tailscaleSession` through a loopback proxy; LocalAPI "somewhat incomplete"; no stated production readiness — **flag** | [libtailscale swift README](https://github.com/tailscale/libtailscale/blob/main/swift/README.md) |
| Reverse proxy + TLS | DSM Login Portal reverse proxy + free Let's Encrypt cert on a `synology.me` DDNS name, auto-renewed every 90 days; change default 5000/5001 | [IT-Connect](https://www.it-connect.fr/synology-publier-une-application-web-avec-le-reverse-proxy/) |
| Swift WebDAV client | FilesProvider (amosavian) last released April 2019; no maintained Swift WebDAV library found. Plan to write a thin WebDAV client over `URLSession` (PUT/MKCOL/PROPFIND/HEAD are trivial) | [CocoaPods](https://cocoapods.org/pods/FilesProvider) |

Implication: a single `PUT` over WebDAV with a file-backed background `URLSessionUploadTask` is the only Synology path that keeps uploading after the app suspends. File Station API uploads are multipart form bodies, which you must write to a temp file to use in a background session, and the sid must be refreshed every 7 days. Self-signed certificates on NASes will be common; the app needs a "trust this NAS certificate (fingerprint)" flow rather than disabling TLS.

### 2d. Dropbox, OneDrive, Box, B2/S3, Nextcloud/WebDAV

| Provider | Upload protocol | Integrity | Auth/app rules | Source |
|---|---|---|---|---|
| Dropbox | `files/upload` ≤150 MiB; `upload_session` start/append_v2/finish, appends in 4 MiB multiples, session max 2^41−2^22 bytes, 7-day life, concurrent sessions supported | `content_hash` = SHA-256 per 4 MiB block, then SHA-256 of concatenated digests | Dev apps capped at 500 users; after 50 linked users you have 2 weeks to get production approval or linking freezes; approval "within a few working days" | [SDK docs](https://docs.rs/dropbox-sdk/latest/dropbox_sdk/files/fn.upload_session_start.html), [Dropbox devguide](https://www.dropbox.com/developers/reference/devguide), [.NET hasher](https://dropbox.github.io/dropbox-sdk-dotnet/gh-pages/obj/api/Dropbox.Api.Files.ContentHasher.html) |
| OneDrive (Graph) | `createUploadSession`; fragments multiples of 320 KiB, <60 MiB each, 5–10 MiB recommended, sequential; `@microsoft.graph.conflictBehavior` fail/replace/rename; `deferCommit`; 507 if `fileSize` exceeds quota; `Files.ReadWrite` least privilege | Hash fields exist on driveItem (quickXorHash, sha256Hash on personal) — from training knowledge, **flag** | Standard Entra app registration | [Microsoft](https://learn.microsoft.com/en-us/graph/api/driveitem-createuploadsession?view=graph-rest-1.0) |
| Box | Chunked upload only for files ≥20 MB; per-part digest; 7-day session; commit step verifies integrity | per-part digest header (algorithm not confirmed from the page — **flag**) | Enterprise app approval for business tenants | [Box](https://developer.box.com/guides/uploads/chunked/) |
| S3 / R2 / B2 (S3 API) | `PutObject` ≤5 GB single, multipart beyond; chunked uploads with trailing checksums | `x-amz-checksum-sha256` on PutObject is full-object and S3 rejects mismatches with `BadDigest`; SHA-256 on multipart is composite only; full-object multipart checksums are CRC-only (CRC64NVME default). R2 supports sha256/sha1 on putObject and CRC-64/NVME full-object multipart | Keys never on device: issue pre-signed URLs from the service | [AWS](https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity-upload.html), [R2 changelog](https://developers.cloudflare.com/r2/reference/changelog/) |
| Nextcloud / generic WebDAV | Chunking v2: `MKCOL /uploads/<user>/<id>`, `PUT` chunks 5 MB–5 GB named 1..10000, `MOVE .file` to assemble, `Destination` header on every call, `OC-Total-Length` for early 507, `X-OC-Mtime`, 24 h inactivity expiry | No checksum header documented on that page; verify by `HEAD` size + re-read sample or trust TLS | App passwords | [Nextcloud](https://docs.nextcloud.com/server/stable/developer_manual/client_apis/WebDAV/chunking.html) |

Pricing for a service-owned escrow bucket: R2 Standard $0.015/GB-month, Class A $4.50/M, Class B $0.36/M, egress free, 10 GB free tier; IA $0.01/GB-month with $0.01/GB retrieval and 30-day minimum ([Cloudflare](https://developers.cloudflare.com/r2/pricing/)). Backblaze B2 $6.95/TB-month ($0.00695/GB), first 10 GB free, egress free up to 3× stored then $0.01/GB, Class D $0.004 per 10k ([Backblaze](https://www.backblaze.com/cloud-storage/pricing)). A heavy user at 200 pages/month ≈ 150 MB/month of PDF/A; even 10 GB/user after years costs $0.15/month on R2.

### 2e. iOS background execution

- Background `URLSession` runs transfers in a separate process and survives app suspension and system termination; the app is relaunched with the same identifier. If the user force-quits from the app switcher, all transfers are cancelled and the app is **not** relaunched until the user opens it ([Apple](https://developer.apple.com/documentation/foundation/urlsessionconfiguration/background(withidentifier:))).
- Only file-backed uploads work; data/stream uploads fail once the app exits; delegate required; HTTP(S) only; redirects always followed ([Apple](https://developer.apple.com/documentation/foundation/downloading-files-in-the-background)).
- `isDiscretionary` defaults to false but is treated as true for any transfer started while the app is in the background ([Apple](https://developer.apple.com/documentation/foundation/urlsessionconfiguration/isdiscretionary)). So start uploads while the capture screen is in the foreground, i.e. immediately after capture.
- Rate limiter: each background relaunch increases the delay before new tasks start; resets to 0 when the app comes to the foreground. Apple: use one session, enqueue many tasks at once, and "perform fewer, larger transfers" if you would need thousands of tasks ([Apple](https://developer.apple.com/documentation/foundation/downloading-files-in-the-background)).
- Resumable uploads are natively supported by `URLSession` since iOS 17 (WWDC23 10006) and Apple points to the IETF `draft-ietf-httpbis-resumable-upload` for server-side design; DTS warns it is "not exactly the well-trodden path" ([Quinn, thread 14853](https://developer.apple.com/forums/thread/14853), [thread 849761](https://developer.apple.com/forums/thread/849761)).
- A developer reported 20 GB+ background uploads stalled for days by energy/data budget policy even with `isDiscretionary=false`; DTS called power management "an implementation detail" that changes between releases ([thread 849761](https://developer.apple.com/forums/thread/849761)). Our files are small (single-digit MB), which is the easy case.
- `BGProcessingTask` can take hours to be granted; `BGContinuedProcessingTask` (iOS 26+) must be submitted from a foreground user action, shows a Live Activity with progress, can be cancelled by the user or killed by the system, and supports `.queue`/`.fail` submission strategies; swiping the app away cancels it silently ([Apple](https://developer.apple.com/documentation/backgroundtasks/performing-long-running-tasks-on-ios-and-ipados)). Field reports on iOS 26.0 reliability are mixed ([forum](https://developer.apple.com/forums/thread/801126)).
- Low Power Mode is one of seven scheduling factors (critically low battery, Low Power Mode, app usage, app switcher removal, Background App Refresh switch, system budgets, rate limiting). It mainly gates Background App Refresh; `BGProcessingTask` is largely unaffected because it runs on charger; "most of the seven factors apply" to discretionary URLSession transfers ([WWDC20 10063 transcript](https://nonstrict.eu/wwdcindex/wwdc2020/10063/)).

### 2f. Durability design

Reference points: Dropbox `content_hash`, Drive `sha256Checksum`, S3 `BadDigest` rejection, Synology `SYNO.FileStation.MD5`, Nextcloud 507-on-quota, Graph 507 `Insufficient Storage`, Drive 403 quota errors, `CKError.quotaExceeded`. Every target either (a) verifies a client-supplied digest on write (S3-compatible), (b) exposes a server-computed digest after write (Drive, Dropbox, Synology MD5 job), or (c) exposes nothing (WebDAV, SMB) and must be verified by `HEAD` size plus a sampled re-read. Design in section 4.

### 2g. Naming and metadata sidecars

- paperless-ngx is the de-facto reference: default filename is the internal id (`0000123.pdf`); templates like `{{ created_year }}/{{ correspondent }}/{{ title }}`; invalid characters `: \ /` become dashes; duplicate names get `_01`, `_02`; versions `_v1`; an archive serial number (ASN) can be printed on the physical paper ([paperless-ngx docs](https://github.com/paperless-ngx/paperless-ngx/blob/main/docs/advanced_usage.md)). It keeps the original next to a PDF/A archive copy (community sources; official doc not retrieved).
- Finder tags survive iCloud Drive; nothing else in xattrs reliably does, and Drive/Synology drop xattrs entirely (no evidence either preserves them). So the portable metadata carriers are: the PDF itself (Info dictionary + XMP packet) and a JSON sidecar.

### 2h. Sync-engine landscape

| Engine | Swift/iOS | Model | File/blob support | Licence / price | Verdict for this project | Source |
|---|---|---|---|---|---|---|
| CloudKit + `CKSyncEngine` | Native, iOS 17+ | Server-client, user's iCloud quota | `CKAsset` up to 50 GB (forum) | Free with Apple account | Good for the per-user ledger on Apple platforms; useless for Drive/NAS fan-out | [forum](https://developer.apple.com/forums/thread/827897) |
| PowerSync | Native Swift SDK (Rust core since v1.14) | Postgres/MongoDB → SQLite, writes via your backend | Attachment queue built in, **alpha on Swift**, `Data` only (no streaming) | Cloud Free: 2 GB synced, 500 MB hosted, 50 concurrent; Pro from $49/mo; self-host "source-available" Open Edition | Candidate for the multi-tenant ledger later; not for the file pipeline | [docs](https://docs.powersync.com/client-sdk-references/swift), [attachments](https://docs.powersync.com/usage/use-case-examples/attachments-files), [pricing](https://www.powersync.com/pricing) |
| ElectricSQL | TypeScript/Elixir only | Read-path shapes over HTTP; writes are yours | None | Open source | No | [electric.ax](https://electric.ax/docs/intro) |
| Replicache / Zero | No Swift | Replicache in maintenance mode; Zero had no offline writes in beta | None | Free (Replicache) | No | [replicache.dev](https://replicache.dev/), [issue](https://bugs.rocicorp.dev/issue/4019) |
| Ditto | Swift SDK | P2P CRDT mesh | Attachments, but no third-party storage targets | Free: 10 devices, 2 GB, 5 GB transfer; Pro/Enterprise contact sales | No (wrong problem) | [pricing](https://www.ditto.com/pricing) |
| rclone-style connectors | Write in Swift | Per-backend upload/verify/list adapters | Native | — | Yes, this is the shape of the delivery layer | — |

## 3. Options compared

| Option for "canonical copy" | Time to durable | Works if user's storage is full/expired | Zero-interaction friendly | Privacy | Cost to us | Fit |
|---|---|---|---|---|---|---|
| A. Device sandbox only, then best-effort fan-out | 0 s to local, unbounded to remote | n/a | Yes | Best | $0 | Fails the guarantee (force-quit, lost phone) |
| B. iCloud Drive container as canonical, others mirrored | seconds–minutes, system-controlled | No (quota) | Yes | Apple-controlled | $0 | Good default for Apple-only users |
| C. User's first configured destination is canonical (Drive/NAS/iCloud), N-of-M status | seconds while in foreground | No | Mostly | User-owned | $0 | Right for v1 single-user |
| D. Service-owned E2EE escrow bucket (R2/S3) canonical + mirrors | ~1 s (small PDF to R2 from foreground) | Yes | Yes | Needs E2EE keys on device | ~$0.015/GB-month | Right for the App Store/service phase |
| E. Third-party sync engine (PowerSync/Ditto) holds the PDFs | seconds | Yes | Yes | Vendor-held unless encrypted | $49+/mo + per-GB | Over-engineered, alpha file support |

Destination-by-destination:

| Destination | Protocol to use | Background-upload-safe | Verify after write | Resumable | Hard limits that matter |
|---|---|---|---|---|---|
| iCloud Drive | Ubiquity container `Documents/` + `NSFileCoordinator` | Yes (system daemon) | `ubiquitousItemIsUploaded` only; no hash exposed | System-managed | 50 GB/file (flag); user quota |
| Google Drive | REST v3 resumable, `drive.file` | Yes if chunk PUTs are file-backed | `sha256Checksum` field | 1-week session | 124-byte appProperties; names not unique; 750 GB/day |
| Synology | WebDAV HTTPS `PUT` (primary); File Station `SYNO.FileStation.Upload` (secondary) | WebDAV yes; File Station multipart only if body is written to a temp file | WebDAV: HEAD + sampled re-read; File Station: `SYNO.FileStation.MD5` job | Neither (re-upload whole file; files are small) | sid 7-day expiry; certificate trust; reachability |
| Dropbox | `upload_session` (or `files/upload` <150 MiB) | Yes | `content_hash` | 7-day session | Production approval at 50 users |
| OneDrive | Graph `createUploadSession` | Yes | hash fields (flag) | Session with sliding expiry | 320 KiB fragment alignment |
| S3/R2/B2 | Pre-signed `PutObject` with `x-amz-checksum-sha256` | Yes | Server rejects on mismatch | Multipart only above 5 GB (not needed) | Keys must stay server-side |

## 4. Recommendation for this project

**Source of truth = local SQLite ledger (WAL mode) + content-addressed file store, with an outbox-driven sync engine you write yourself.** Do not put the ledger in iCloud Drive as a file; put it in SQLite and optionally mirror it with CloudKit (`CKSyncEngine`) for multi-device, later PowerSync for the service.

1. **Capture path (sub-second):** write the raw capture to `Library/Application Support/vault/blobs/<sha256>` with an atomic rename, insert a `documents` row and one `outbox` row per enabled destination in the same transaction, then immediately enqueue a file-backed background `URLSessionUploadTask` *while still in the foreground* (so it is not treated as discretionary). Do not wait for OCR/classification to upload: upload the original image/PDF first, and upload the enriched archival PDF/A + sidecar as a second, idempotent version. Users get a "captured" tick in ~1 s when the service escrow bucket (option D) acknowledges; for pure user-owned mode (option C) the tick waits for the first destination.
2. **Outbox state machine per (document, destination):** `pending → uploading(session_uri, bytes_sent) → uploaded(remote_id, etag) → verified(sha256_match_at) → failed(reason, retry_at)`. Persist resumable session URIs/upload IDs so a kill or reboot resumes rather than restarts. Exponential backoff with jitter capped at 1 h; permanent failures (`401/403` expired auth, `507`/quota, Drive 403 storageQuotaExceeded, `CKError.quotaExceeded`) move the destination to `needs_attention` and surface a single banner, never a modal during scanning.
3. **Verification:** compute SHA-256 once at capture. Drive: compare `sha256Checksum`. S3/R2: send `x-amz-checksum-sha256` so the server rejects corruption. Dropbox: compute `content_hash` locally. Synology File Station: start an `SYNO.FileStation.MD5` job (keep an MD5 alongside the SHA-256 for this). WebDAV/SMB: `HEAD` size match plus a full re-read for the first N files per destination and random 1-in-20 thereafter. Only `verified` counts toward the commit quorum.
4. **"Safe to shred" state:** default quorum = 1 verified remote copy (escrow or user destination), displayed as a single green state; a second state "fully replicated" when all enabled destinations are verified. Keep the local blob until fully replicated plus 7 days, then it becomes cache. Expose the counts per destination in a quiet status screen; the scanning screen only shows the tick.
5. **Retry across kills/reboots:** one background `URLSession` identifier for the whole app; on launch (user or system), recreate the session, reconcile `getAllTasks()` against the outbox, and re-enqueue what is missing. Register a `BGProcessingTask` (network required) as a nightly sweep and, on iOS 26, start a `BGContinuedProcessingTask` when the user leaves the capture screen with more than a few pending uploads so the Live Activity shows progress. Treat force-quit as the known hole and tell the user once.
6. **iCloud Drive connector:** write via `NSFileCoordinator` into `Documents/Vault/YYYY/…`, mark `uploaded` when `ubiquitousItemIsUploadedKey` flips (via `NSMetadataQuery`), mark `verified` on size equality (no hash available). Set the Finder tag xattr with the document's tags since that is the one xattr that survives.
7. **Google Drive connector:** `drive.file` scope only; create `Vault/` once and store its ID; resumable upload with 1 MiB-aligned chunks (multiple of 256 KB) from a temp file per chunk so it works in a background session; set `appProperties={"sid": <8-char id>, "h": <first 32 hex of sha256>}` (fits 124 bytes) and `contentHints.indexableText` with the extracted text (≤128 KB) so Drive's own search finds the document even if its PDF indexer stops at 1 MB/80 pages.
8. **Synology connector:** ship WebDAV first (one `PUT`, `MKCOL` for folders, `HEAD` to verify), then File Station API for users who prefer DSM accounts; require HTTPS, support a certificate-fingerprint trust prompt, and document three reachability recipes: LAN only, Tailscale (official SPK), DSM reverse proxy + Let's Encrypt. Do not attempt QuickConnect. Evaluate TailscaleKit only as a later convenience.
9. **Naming:** `YYYY/YYYY-MM-DD_<sender-slug>_<doctype-slug>_<8-char-id>.pdf`, ASCII, ≤100 chars, immutable after commit; duplicates get `_01`. Same path layout in every destination so a user can move between them without re-indexing.
10. **Metadata carriers (all three, always):** (a) PDF Info + XMP packet inside the PDF/A (dc:title, dc:subject for tags, dc:date, custom `vault:` namespace with id, sha256, sender, doctype, amounts); (b) `<same-name>.json` sidecar with the full extraction and the Claude output; (c) a per-destination `_vault/index.jsonl` append-only manifest rewritten monthly, so a fresh install can rebuild the ledger from any one destination.
11. **Multi-tenant service:** own an R2 bucket (free egress) as the escrow/first-commit target with per-user envelope encryption (random per-document key wrapped by a user key in Keychain/iCloud Keychain; Claude processing happens on-device or via a short-lived decrypted stream the service never persists). Keep user-owned destinations as mirrors the service can also write on the user's behalf (server-side Drive/Dropbox tokens, which also fixes "phone was off for a week"). Never make the NAS reachable from the service; the phone remains the only writer to a NAS.

## 5. Risks and unknowns

- Apple power management is explicitly "an implementation detail"; background upload timing can regress between iOS releases. Mitigation: start transfers in the foreground, keep them small, escrow bucket.
- Force-quit cancels everything with no relaunch; there is no API workaround.
- iCloud Drive has no latency or integrity SLA and exposes no hash; treat it as the weakest "verified" state.
- Google verification: brand verification needs a real homepage and privacy policy on an owned domain before TestFlight-scale testing; the 100-user cap applies only if we touch sensitive/restricted scopes, so stay on `drive.file`.
- Drive's content indexing limits (1 MB text, 80 pages) came from a Google Cloud doc, not the consumer Drive help page; verify empirically with a 100-page text-layer PDF.
- Synology's official API guide is DSM 6-era; `otp_code` support and v3 upload semantics on DSM 7 are only community-documented. Self-signed certificates and NAT are the main support burden.
- `CKAsset` 50 GB and the iCloud Drive 50 GB per-file numbers rest on forum/Apple-staff posts, not current doc pages.
- Dropbox: production approval becomes mandatory at 50 users; OneDrive hash field names and Box per-part digest algorithm are unverified here.
- PowerSync attachments on Swift are alpha and buffer whole files in memory; TailscaleKit's LocalAPI is incomplete.
- Unknown: whether SMB folders granted through the Files picker remain writable from a background `URLSession` (they do not; writes need the app process) — confirms SMB is foreground-only.

## 6. Open questions for the founder

1. Is a service-owned, end-to-end-encrypted escrow bucket acceptable for v1, or must v1 be strictly user-owned storage? This decides whether "captured in ~1 s" can be an honest promise.
2. Default quorum: is one verified remote copy enough for the green tick, or do you want two (e.g. iCloud + Drive) before shredding?
3. Do you own a domain with a homepage and privacy policy today (needed for Google brand verification before public TestFlight)?
4. Synology: is your NAS reachable today via Tailscale, DDNS+reverse proxy, or LAN only? Which DSM version? Do you use 2FA on the DSM account (affects File Station API login)?
5. Should the archival PDF/A overwrite the first-uploaded original in each destination, or should both be kept (`original/` + `archive/` like paperless-ngx)?
6. Multi-device now (phone + Mac/iPad viewing) or later? This decides whether CloudKit `CKSyncEngine` goes into v1 for the ledger.
7. Are Dropbox/OneDrive/Box required for launch, or can they wait until after Drive/iCloud/Synology?

## 7. Sources

- Apple, background(withIdentifier:): https://developer.apple.com/documentation/foundation/urlsessionconfiguration/background(withidentifier:)
- Apple, Downloading files in the background: https://developer.apple.com/documentation/foundation/downloading-files-in-the-background
- Apple, isDiscretionary: https://developer.apple.com/documentation/foundation/urlsessionconfiguration/isdiscretionary
- Apple, Performing long-running tasks (BGContinuedProcessingTask): https://developer.apple.com/documentation/backgroundtasks/performing-long-running-tasks-on-ios-and-ipados
- Apple, Synchronizing documents in the iCloud environment: https://developer.apple.com/documentation/uikit/synchronizing-documents-in-the-icloud-environment
- Apple, ubiquitousItemIsUploadedKey: https://developer.apple.com/documentation/foundation/urlresourcekey/ubiquitousitemisuploadedkey
- Apple, ubiquitousItemHasUnresolvedConflictsKey: https://developer.apple.com/documentation/foundation/urlresourcekey/ubiquitousitemhasunresolvedconflictskey
- Apple, CKAsset: https://developer.apple.com/documentation/cloudkit/ckasset
- Apple forum, CKAsset limits (Apple engineer): https://developer.apple.com/forums/thread/827897
- Apple forum, Moving to Fewer, Larger Transfers (Quinn): https://developer.apple.com/forums/thread/14853
- Apple forum, background uploads stalled by budget policy: https://developer.apple.com/forums/thread/849761
- Apple forum, BGContinuedProcessingTask on iOS 26 release: https://developer.apple.com/forums/thread/801126
- Apple, Providing access to directories: https://developer.apple.com/documentation/uikit/providing-access-to-directories
- Apple forum, security-scoped bookmarks on iOS: https://developer.apple.com/forums/thread/773373
- Apple, CSSearchableItemAttributeSet.contentURL: https://developer.apple.com/documentation/corespotlight/cssearchableitemattributeset/contenturl
- WWDC20 Background execution demystified (transcript index): https://nonstrict.eu/wwdcindex/wwdc2020/10063/
- Apple Community, iCloud Drive 50 GB file limit: https://discussions.apple.com/thread/6603001?page=1
- Eclectic Light, what gets synced in iCloud Drive: https://eclecticlight.co/2026/05/12/what-gets-synced-in-icloud-drive/
- Google, Drive API scopes: https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- Google, OAuth verification requirements: https://support.google.com/cloud/answer/13464321
- Google, OAuth verification FAQ: https://support.google.com/cloud/answer/13463817
- Google, Manage uploads: https://developers.google.com/workspace/drive/api/guides/manage-uploads
- Google, Usage limits: https://developers.google.com/workspace/drive/api/guides/limits
- Google, Custom file properties: https://developers.google.com/workspace/drive/api/guides/properties
- Google, Search files: https://developers.google.com/workspace/drive/api/guides/search-files
- Google, Search query terms: https://developers.google.com/workspace/drive/api/guides/ref-search-terms
- Google, files resource: https://developers.google.com/workspace/drive/api/reference/rest/v3/files
- Google Cloud, Drive search index limits: https://docs.cloud.google.com/gemini/enterprise/docs/connectors/gdrive
- Synology, File Station Official API guide (PDF): https://global.download.synology.com/download/Document/Software/DeveloperGuide/Package/FileStation/All/enu/Synology_File_Station_API_Guide.pdf
- Synology, WebDAV Server help: https://kb.synology.com/th-th/DSM/help/WebDAVServer/webdav_server?version=7
- Synology, WebDAV tutorial: https://www.synology.com/hu-hu/knowledgebase/tutorials/610
- pmilano1, unofficial DSM 7 API reference: https://github.com/pmilano1/synology-dsm-api
- zbjdonald, synology-drive-api: https://github.com/zbjdonald/synology-drive-api
- Synology community, Drive API: https://community.synology.com/enu/forum/1/post/149809
- Tailscale on Synology: https://tailscale.com/kb/1131/synology
- libtailscale Swift (TailscaleKit): https://github.com/tailscale/libtailscale/blob/main/swift/README.md
- WunderTech, Synology remote access options: https://www.wundertech.net/synology-nas-remote-access/
- IT-Connect, DSM reverse proxy + Let's Encrypt: https://www.it-connect.fr/synology-publier-une-application-web-avec-le-reverse-proxy/
- FilesProvider (CocoaPods): https://cocoapods.org/pods/FilesProvider
- Dropbox SDK, upload_session_start: https://docs.rs/dropbox-sdk/latest/dropbox_sdk/files/fn.upload_session_start.html
- Dropbox developer guide (production approval): https://www.dropbox.com/developers/reference/devguide
- Dropbox content hash: https://dropbox.github.io/dropbox-sdk-dotnet/gh-pages/obj/api/Dropbox.Api.Files.ContentHasher.html
- Microsoft Graph, createUploadSession: https://learn.microsoft.com/en-us/graph/api/driveitem-createuploadsession?view=graph-rest-1.0
- Box, chunked uploads: https://developer.box.com/guides/uploads/chunked/
- AWS, Checking object integrity for uploads: https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity-upload.html
- Cloudflare R2 pricing: https://developers.cloudflare.com/r2/pricing/
- Cloudflare R2 changelog (checksums): https://developers.cloudflare.com/r2/reference/changelog/
- Backblaze B2 pricing: https://www.backblaze.com/cloud-storage/pricing
- Nextcloud chunked upload v2: https://docs.nextcloud.com/server/stable/developer_manual/client_apis/WebDAV/chunking.html
- paperless-ngx advanced usage (file naming): https://github.com/paperless-ngx/paperless-ngx/blob/main/docs/advanced_usage.md
- PowerSync Swift SDK: https://docs.powersync.com/client-sdk-references/swift
- PowerSync attachments: https://docs.powersync.com/usage/use-case-examples/attachments-files
- PowerSync pricing: https://www.powersync.com/pricing
- ElectricSQL docs: https://electric.ax/docs/intro
- Replicache (maintenance mode): https://replicache.dev/
- Zero offline writes issue: https://bugs.rocicorp.dev/issue/4019
- Ditto pricing: https://www.ditto.com/pricing
