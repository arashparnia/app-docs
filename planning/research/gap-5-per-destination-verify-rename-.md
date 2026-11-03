# Gap 5: per-destination commit, verify, rename and audit protocol (iCloud Drive, Google Drive, Synology)

Research date: 2026-11-03. Gap-filling round for the storage, dedup, output and apple reports. The shared web-search budget was exhausted when this round started, so every finding below comes from directly fetched primary sources (Apple doc JSON endpoints, Google reference pages, Synology's official PDFs extracted with `pdftotext`, RFC 4918/6750 text, ISO 32000-1 text, veraPDF rules). Items I could not confirm are marked **unknown** or **flag**. Synology Knowledge Center HTML pages are JavaScript-rendered and returned only titles; the two Synology PDFs are the only official Synology sources used.

## 1. Executive summary

- Resolve the immutability-vs-rename contradiction by splitting identity from label: the archival PDF's **bytes are immutable from the first commit**; the **name/path is a mutable label** changed by a metadata-only operation on every destination (Drive `files.update` name/parents, WebDAV `MOVE` with `Overwrite: F`, `NSFileCoordinator` move + `item(at:didMoveTo:)`). None of the three creates a second copy. Classification results go into the filename, the JSON sidecar and destination-native metadata, not into the PDF bytes.
- iCloud verification is `NSMetadataUbiquitousItemIsUploadedKey == true` with `NSMetadataUbiquitousItemUploadingErrorKey == nil`, observed through a live `NSMetadataQuery` (Apple explicitly says not to poll the key inside a coordinated read). There is no server hash; bind each "verified" row to a hash of the archived `ubiquityIdentityToken` and freeze the destination on `NSUbiquityIdentityDidChange`.
- Google Drive gets the strongest guarantee: pre-generated `files.generateIds` make the create idempotent (retry after success returns `409`, no duplicate), and the output-only `sha256Checksum` is compared to the local digest before "verified". A background `URLSessionUploadTask` carries a frozen `Authorization: Bearer` header; the fix is not to keep it alive but to treat `401 invalid_token` as a benign retry: refresh via `GIDGoogleUser.refreshTokensIfNeeded`, send the empty `PUT Content-Range: bytes */N` status probe, and resume the week-long session.
- Synology: `PUT` over WebDAV/HTTPS into an `_inbox/` collection, `MOVE` to the final path, `PROPFIND Depth: 0` for size, and when a File Station session exists, `SYNO.FileStation.MD5` (start/status, DSM 6.0+) against a stored MD5. DSM 7 2FA is handled with `SYNO.API.Auth` v6 `otp_code` + `enable_device_token=yes` once, then `device_id=<did>` forever (errors 403/404/406 documented).
- ATS cannot be loosened per-host at runtime: Apple states that with ATS enabled "you can no longer loosen trust evaluation" in the challenge delegate. The storage report's "trust this fingerprint" prompt will not work for a self-signed NAS. Ship three supported transport recipes instead: DSM Let's Encrypt on a `synology.me` DDNS name, Tailscale + `tailscale cert` (Let's Encrypt for the MagicDNS name), or a user-installed root profile.
- Deterministic re-emission: `/ID[0]` and `xmpMM:DocumentID` derived from the capture-time document id, `CreationDate` = capture time, image streams and OCR JSON stored once and replayed, so a re-emitted PDF is byte-identical unless content changed; `/ID[1]`, `xmpMM:InstanceID` and `ModDate` change per emission (ISO 32000-1 §14.4).
- Audit: Drive `changes.list` from a stored start token (tokens "don't expire"); iCloud a long-lived `NSMetadataQuery` whose `DidUpdate` userInfo carries added/changed/removed arrays (iOS 8+); Synology `PROPFIND Depth: 1` per year collection or `SYNO.FileStation.List` with `additional=size,time`, plus sampled MD5 jobs.

## 2. Findings

### 2a. The contradiction in the storage report, stated precisely

| Item | Says | Conflict |
|---|---|---|
| Rec. 1 | upload the original first, "upload the enriched archival PDF/A + sidecar as a second, idempotent version" | re-writes bytes after commit |
| Rec. 9 | name template is "immutable after commit" | but the name needs classifier output that arrives seconds later |
| 2a implication | "we never rewrite a file" so iCloud conflicts cannot arise | contradicts rec. 1 |

The clean resolution is a three-way split of what "immutable" applies to:

1. **Document identity** (`docId`, assigned at capture) never changes.
2. **Version bytes** never change: a given `(docId, version)` is one SHA-256, and every destination holds exactly that object. A later version is a new object only if we ever choose to re-emit (section 2e); v1 recommends never re-emitting after commit.
3. **Label** (name, folder) is mutable metadata and is changed in place on all three destinations.

### 2b. iCloud Drive (ubiquity container)

| Fact | Value | Source |
|---|---|---|
| Upload-complete signal | `ubiquitousItemIsUploadedKey` (iOS 5+): "The value is true if the system uploads this item to iCloud"; Apple: "don't poll this key from within a block that you pass to coordinate(readingItemAt:...)... Instead, use NSMetadataQuery or an NSFilePresenter delegate" | https://developer.apple.com/documentation/foundation/urlresourcekey/ubiquitousitemisuploadedkey |
| Upload error signal | `ubiquitousItemUploadingErrorKey` (iOS 7+): "error object that indicates why uploading the item to iCloud fails"; metadata twin `NSMetadataUbiquitousItemUploadingErrorKey` "describes the problem that occurred when uploading the item to iCloud failed" | https://developer.apple.com/documentation/foundation/urlresourcekey/ubiquitousitemuploadingerrorkey ; https://developer.apple.com/documentation/foundation/nsmetadataubiquitousitemuploadingerrorkey |
| Metadata attribute | `NSMetadataUbiquitousItemIsUploadedKey` (iOS 5+): "Boolean indicating whether the item has been uploaded to the cloud" | https://developer.apple.com/documentation/foundation/nsmetadataubiquitousitemisuploadedkey |
| Query mechanics | Two phases (gather, live update); `NSMetadataQueryDidFinishGathering`, `NSMetadataQueryDidUpdate`; batching interval default 1.0 s; `disableUpdates()` while reading results; userInfo keys `NSMetadataQueryUpdateAddedItemsKey/ChangedItemsKey/RemovedItemsKey` (iOS 8+) | https://developer.apple.com/documentation/foundation/nsmetadataquery ; https://developer.apple.com/documentation/foundation/nsmetadataqueryupdateremoveditemskey |
| Why not file-system APIs | "iOS apps use NSMetadataQuery rather than file system APIs to discover documents in an iCloud container... the document data may not physically exist on the local file system" | https://developer.apple.com/documentation/uikit/synchronizing-documents-in-the-icloud-environment |
| Moving a local file in | `FileManager.setUbiquitous(true, itemAt:destinationURL:)`: physically removes the file from the sandbox, "performs a coordinated write... which can block for a long time", never on the main thread; you create intermediate directories yourself | https://developer.apple.com/documentation/foundation/filemanager/setubiquitous(_:itemat:destinationurl:) |
| Rename | `coordinate(writingItemAt:options:writingItemAt:options:error:byAccessor:)` does "the canonical lock ordering that is required to prevent a potential deadlock"; `.forMoving` on the source ("has no effect on files", safe to use); after `moveItem`, call `item(at:didMoveTo:)` "from a coordinated write block" to notify presenters | https://developer.apple.com/documentation/foundation/nsfilecoordinator/coordinate(writingitemat:options:writingitemat:options:error:byaccessor:) ; https://developer.apple.com/documentation/foundation/nsfilecoordinator/writingoptions/formoving ; https://developer.apple.com/documentation/foundation/nsfilecoordinator/item(at:didmoveto:) |
| Identity token | `ubiquityIdentityToken` (iOS 6+): nil when iCloud unavailable or no user; archive it and compare with `isEqual(_:)`; posted together with `NSUbiquityIdentityDidChange`; "CloudKit clients should not use this token" | https://developer.apple.com/documentation/foundation/filemanager/ubiquityidentitytoken |
| What to do on change | Design Guide: compare new token to archived; "If the values are different, the previously used account is now unavailable. Discard any changes, empty your iCloud-related data caches, and refresh all iCloud-related user interface elements"; keep working into the local container and "move the new content to iCloud" when an account is back; signing out sets the token to nil; airplane mode keeps it | https://developer.apple.com/library/archive/documentation/General/Conceptual/iCloudDesignGuide/Chapters/iCloudFundametals.html |
| Local eviction | `evictUbiquitousItem(at:)` "removes only the local version"; "Don't use a coordinated write to perform this operation"; downloading status enum `current` / `downloaded` (stale) / `notDownloaded` | https://developer.apple.com/documentation/foundation/filemanager/evictubiquitousitem(at:) ; https://developer.apple.com/documentation/foundation/urlubiquitousitemdownloadingstatus |

Not in any Apple page I could fetch (**unknown**): whether a rename inside the container re-uploads data or only metadata, and whether a user deletion in Files leaves the item visible to the query during the "Recently Deleted" window. The protocol below does not depend on either.

**Commit protocol (iCloud).** (1) Write the PDF to `Library/Application Support/vault/blobs/<sha256>` and fsync. (2) Copy to a staging path, then off the main thread call `setUbiquitous(true, ..., destinationURL: <container>/Documents/PaperVault/<YYYY>/<provisional name>)`, after creating the year directory. (3) One app-lifetime `NSMetadataQuery` with `searchScopes = [NSMetadataQueryUbiquitousDocumentsScope]`, predicate on `NSMetadataItemPathKey BEGINSWITH <container>/Documents/PaperVault`, `notificationBatchingInterval = 1`. (4) On `DidFinishGathering` and each `DidUpdate`, for every item in the ledger with state `uploading`: if `NSMetadataUbiquitousItemUploadingErrorKey != nil` record `failed(error)`; else if `NSMetadataUbiquitousItemIsUploadedKey == true` and `NSMetadataItemFSSizeKey == local size`, record `verified(size, identityHash, at)`. (5) The verified row stores `SHA-256(archived ubiquityIdentityToken)`; only rows whose identity hash equals the current one count toward quorum.

**Rename protocol (iCloud).** When the final name is known: coordinated two-URL write (`.forMoving` on old, `.forReplacing` on new), `FileManager.moveItem`, `item(at:didMoveTo:)`, then update the ledger path. If a file already exists at the destination, append `_01`. Rename is done regardless of whether the upload has finished; the query continues to report the item at its new path, and verification is evaluated against the ledger's current path.

**Identity-change protocol.** At launch compare `ubiquityIdentityToken` to the archived token. On `NSUbiquityIdentityDidChange` or mismatch: set the iCloud destination to `paused(account_changed)`, stop treating its `verified` rows as current (they remain in the ledger tagged with the old identity hash), keep writing new documents to the local blob store and to the other destinations, and offer a single banner "iCloud account changed; re-link to keep saving there". When a token returns, re-run the gather phase and reconcile.

### 2c. Google Drive v3 (`drive.file`)

| Fact | Value | Source |
|---|---|---|
| Idempotent create | `files.generateIds` (default 10, max 1,000; scopes include `drive.file`); pass the id in the create/upload metadata; "If the file is successfully created or copied, subsequent retries return a 409 Conflict"; resumable guide: safe to retry "with the same pre-generated ID" after indeterminate errors, "no duplicate files are created" | https://developers.google.com/workspace/drive/api/guides/create-file ; https://developers.google.com/workspace/drive/api/reference/rest/v3/files/generateIds ; https://developers.google.com/workspace/drive/api/guides/manage-uploads |
| Resumable session | `POST .../upload/drive/v3/files?uploadType=resumable` with JSON metadata, `X-Upload-Content-Type/Length`; `Location` = session URI, "expires after one week"; chunks multiples of 256 KB; status probe = empty `PUT` with `Content-Range: bytes */N` → 308 + `Range`, 404 = restart; "Use PATCH instead when updating an existing file" | https://developers.google.com/workspace/drive/api/guides/manage-uploads |
| Verify | `md5Checksum`, `sha1Checksum`, `sha256Checksum` are output-only, populated for binary content stored in Drive; `headRevisionId`, `version` ("monotonically increasing... reflects every change made to the file on the server"), `size`, `trashed`, `explicitlyTrashed` | https://developers.google.com/workspace/drive/api/reference/rest/v3/files |
| Rename / move | `files.update` "supports patch semantics"; metadata URI `PATCH https://www.googleapis.com/drive/v3/files/{fileId}` needs no upload; move with `addParents`/`removeParents`; a file has exactly one parent | https://developers.google.com/workspace/drive/api/reference/rest/v3/files/update ; https://developers.google.com/workspace/drive/api/guides/folder |
| Audit | `changes.getStartPageToken` → `changes.list` oldest first; `includeRemoved`; "The page token doesn't expire"; Change resource `removed` = "removed from this list of changes, for example by deletion or loss of access", `file` present only if not removed; `drive.file` is an accepted scope | https://developers.google.com/workspace/drive/api/guides/manage-changes ; https://developers.google.com/workspace/drive/api/reference/rest/v3/changes/list ; https://developers.google.com/workspace/drive/api/reference/rest/v3/changes |
| Revisions | content updates keep the file id and create revisions; non-kept revisions "purged automatically 30 days after newer content is uploaded"; max 200 `keepForever`; Revision has `md5Checksum` but **no** `sha256Checksum` | https://developers.google.com/workspace/drive/api/reference/rest/v3/revisions ; https://developers.google.com/workspace/drive/api/guides/manage-revisions |
| Scope / Picker | `drive.file` is non-sensitive and covers files the app created or the user opened/selected; the Picker is a "Client-side JavaScript library"; for desktop and mobile it "Can no longer be displayed within an embedded webview"; no native iOS Picker | https://developers.google.com/workspace/drive/api/guides/api-specific-auth ; https://developers.google.com/workspace/drive/picker/guides/overview |
| Tokens | Google documents no numeric access-token lifetime (sample responses show `expires_in: 3920`); refresh tokens: 7-day expiry while the consent screen is in Testing, 100 per client per account (oldest silently invalidated), 6 months unused; Bearer header preferred; `WKWebView` auth gives `disallowed_useragent` | https://developers.google.com/identity/protocols/oauth2 ; https://developers.google.com/identity/protocols/oauth2/native-app |
| iOS SDK | `GIDSignIn.restorePreviousSignIn()` "without interaction"; `GIDGoogleUser.refreshTokensIfNeeded()` refreshes tokens "if they have expired or are about to expire"; `GIDToken.expirationDate` is "estimated" | https://developers.google.com/identity/sign-in/ios/reference/Classes/GIDSignIn ; https://developers.google.com/identity/sign-in/ios/reference/Classes/GIDGoogleUser ; https://developers.google.com/identity/sign-in/ios/reference/Classes/GIDToken |
| 401 semantics | RFC 6750: `invalid_token` = "expired, revoked, malformed"; server "SHOULD respond with the HTTP 401"; "The client MAY request a new access token and retry" | https://www.rfc-editor.org/rfc/rfc6750.txt |
| Background task | "Only upload tasks from a file are supported"; delegate required; redirects always followed; relaunch rate limiter grows per relaunch, resets in foreground; `originalRequest` is "the request object passed when the task was created" | https://developer.apple.com/documentation/foundation/downloading-files-in-the-background ; https://developer.apple.com/documentation/foundation/urlsessiontask/originalrequest |

**How the frozen Bearer token "survives" the token lifetime: it does not need to.** The header must be valid when the server receives the request, and for a 1-10 MB PDF that is seconds after the task starts. The real exposure is the gap between task creation and task start (rate limiter after background relaunch, discretionary scheduling, no network), which can exceed the access-token lifetime. Protocol: refresh with `refreshTokensIfNeeded` immediately before creating each task; make the task a single `PUT` of the whole file to the session URI (no chunk loop in the background); on completion with HTTP 401 (`WWW-Authenticate: Bearer error="invalid_token"`), refresh again, send the `Content-Range: bytes */N` probe, and create a new task from the returned offset using the same session URI (valid one week). Nothing is re-uploaded on the common path. Apple's docs give no way to mutate a task's headers after creation (flag: I could not fetch a DTS statement; the design assumes immutability, which is the safe assumption). Whether the Drive session URI accepts a `PUT` without an `Authorization` header is **unknown** for Drive (GCS documents that behaviour; Drive does not); test it, and do not rely on it.

**Commit protocol (Drive).** (1) At link time: create `PaperVault/` (mimeType `application/vnd.google-apps.folder`) and store its id; create year folders lazily; fetch 100 ids from `generateIds` into a ledger pool. (2) At capture: take an id, initiate the resumable session with `{id, name: provisional, parents: [yearFolderId], appProperties: {sid, h}}` and persist the session URI. (3) Foreground-started background `uploadTask(with: PUT sessionURI, fromFile:)`. (4) On 200/201, parse `fields=id,name,parents,size,sha256Checksum,headRevisionId,version`; `verified` iff `sha256Checksum == local` and `size == local`. On 409 from a restarted session, `files.get` the id and run the same comparison. (5) Persist `version` and `headRevisionId` as the baseline for audit.

**Rename protocol (Drive).** `PATCH /files/{id}` with `{name}`; if the document date moves the file to another year folder, add `addParents=<newYear>&removeParents=<oldYear>` in the same call. Idempotent: re-sending yields the same state. Drive names are not unique, so no collision handling is needed, but keep `_01` for consistency across destinations.

**Folder-selection UX without a native Picker.** Options: (a) app-created `PaperVault` referenced by id; the user may move or rename it anywhere in Drive and the app keeps working because `drive.file` grants access to files it created, by id, not by path; (b) a web Picker hosted by us inside `ASWebAuthenticationSession` (the only Google-sanctioned mobile route); (c) `UIDocumentPickerViewController` through the Google Drive File Provider, which yields a sandbox URL, not a Drive id, and writes through the Drive app in the foreground only, with no checksum. Recommend (a) with an in-app "Move it wherever you like in Drive" line; (b) is a v2 nicety; (c) is unusable for the commit path.

### 2d. Synology (WebDAV first, File Station second)

| Fact | Value | Source |
|---|---|---|
| DSM 7 login | `SYNO.API.Auth` versions 3-7, "6 (Recommended)", examples "based on DSM 7.0"; params `account`, `passwd`, `session`, `format=sid`, `otp_code` (3+), `enable_syno_token`, `enable_device_token` ("Omit 2-factor authentication (OTP) with a device id for the next login request", 6+), `device_name`, `device_id` (6+); response `sid`, `did`, `synotoken`; errors 400 bad credentials, 401 disabled, 402 denied, **403 "2-factor authentication code required"**, **404 "Failed to authenticate 2-factor authentication code"**, **406 "Enforce to authenticate with 2-factor"**, 407 blocked IP, 408-410 password expiry; `_sid=<sid>` or cookie on each call; error 106 "Session timeout" | DSM Login Web API Guide (2023): https://global.download.synology.com/download/Document/Software/DeveloperGuide/Os/DSM/All/enu/DSM_Login_Web_API_Guide_enu.pdf |
| MD5 job | `SYNO.FileStation.MD5` v2, DSM 6.0+: `start&file_path="/share/x.pdf"` → `taskid`; `status&taskid` → `{finished, md5}`; `stop` | File Station Official API Guide: https://global.download.synology.com/download/Document/Software/DeveloperGuide/Package/FileStation/All/enu/Synology_File_Station_API_Guide.pdf |
| Rename | `SYNO.FileStation.Rename` v2: `path=["/share/a.pdf"]&name=["b.pdf"]`, optional `additional=size,time`; returns `<file>` objects | same |
| Upload | `SYNO.FileStation.Upload` v2/v3 multipart, `path`, `create_parents`, `overwrite` (v2 true/false; v3 overwrite/skip; error if omitted and file exists), `mtime/crtime/atime` in ms, file part last | same |
| List for audit | `SYNO.FileStation.List&method=list&folder_path=...&additional=["size","time","real_path"]`; `<file>` has `path`, `name`, `isdir`, `additional.size`, `additional.time` (atime/mtime/ctime/crtime) | same |
| WebDAV MOVE | RFC 4918 §9.9: "logical equivalent of a copy, followed by consistency maintenance, followed by a delete of the source... in a single operation"; "MOVE is frequently used by clients to rename a file"; `DAV:creationdate` "SHOULD remain the same"; `Overwrite: F` → 412 Precondition Failed if the destination exists (§10.6); 201 created / 204 replaced; idempotent | https://www.rfc-editor.org/rfc/rfc4918.txt |
| WebDAV PUT/ETag | §9.7: PUT into a missing parent collection "MUST fail with a 409"; §15.6 `getetag` MUST be defined on resources that return an ETag (whether Synology's WebDAV emits ETags is **unknown**) | same |
| ATS and self-signed | ATS requires a chain to an anchor that "must be part of the client operating system... or be installed on the client by the user or a system administrator", RSA ≥ 2048 / ECC ≥ 256, SHA-256, TLS 1.2, PFS; "When ATS is enabled, you can no longer loosen trust evaluation requirements that way, but you can still tighten them" | https://developer.apple.com/documentation/security/preventing-insecure-network-connections |
| Local addresses | `NSAllowsLocalNetworking` covers unqualified names, `.local` and IP addresses; iOS 10-16 allowed all three by default; "In iOS 17... ATS no longer allows connections to IP addresses by default. Add individual IP addresses and CIDR ranges in the NSExceptionDomains dictionary" | https://developer.apple.com/documentation/bundleresources/information-property-list/nsapptransportsecurity/nsallowslocalnetworking |
| Challenge delegate | Session-level `urlSession(_:didReceive:completionHandler:)` is called "When a session first establishes a connection to a remote server that uses SSL or TLS" (server trust, client cert, NTLM, Negotiate only); Bearer is never a challenge | https://developer.apple.com/documentation/foundation/urlsessiondelegate/urlsession(_:didreceive:completionhandler:) |
| Tailscale certs | `tailscale cert` requests a Let's Encrypt certificate for the MagicDNS name (MagicDNS + HTTPS enabled in the admin console; 90-day expiry; files are not auto-renewed by tailscaled); Synology page: DSM 7 needs the TUN boot task, "access your Synology device from anywhere, without opening firewall ports"; iOS client requires iOS 15+; MDM keys show an iOS "VPN On Demand" menu and `AlwaysOn` policy | https://tailscale.com/kb/1153/enabling-https ; https://tailscale.com/kb/1131/synology ; https://tailscale.com/kb/1020/install-ios ; https://tailscale.com/kb/1315/mdm-keys |

**Unknowns I could not close (Synology KB pages are JS-rendered):** whether DSM 2FA applies to WebDAV Basic auth (community consensus is that file protocols bypass 2FA; treat as **flag**); whether QuickConnect carries anything but Synology's own apps (storage report already says no official statement); whether Synology WebDAV emits `getetag`; WebDAV `MOVE` across shared folders (keep `_inbox/` inside the same share to avoid it).

**Transport decision forced by ATS.** Because trust cannot be loosened in the delegate while ATS is on, and because `NSExceptionDomains` is a build-time list that cannot contain each user's NAS hostname, a self-signed NAS certificate cannot be accepted by a fingerprint prompt without `NSAllowsArbitraryLoads` (an App Review justification and a global downgrade). Supported recipes, in order: (1) DSM's built-in Let's Encrypt on `<name>.synology.me` DDNS (publicly trusted, zero app work, works off-LAN with a port forward or DSM reverse proxy); (2) Tailscale on NAS and phone with `tailscale cert` (publicly trusted, no port forwarding; renewal is the user's job, so the app should detect certificate expiry and say so); (3) user installs the NAS CA as a configuration profile (ATS accepts user-installed anchors). Local IP addresses on iOS 17+ additionally require static `NSExceptionDomains` CIDR entries (`192.168.0.0/16`, `10.0.0.0/8`, `172.16.0.0/12`, `100.64.0.0/10`) and still need a trusted certificate; `.local` names via `NSAllowsLocalNetworking`. SMB is foreground-only (storage report) and QuickConnect is out.

**Commit protocol (Synology, WebDAV).** (1) `MKCOL` `/<share>/PaperVault/_inbox/` and `/<share>/PaperVault/<YYYY>/` once (409 on PUT tells you a parent is missing). (2) Background `uploadTask(with: PUT /<share>/PaperVault/_inbox/<docId>.pdf, fromFile:)` with `Content-Type: application/pdf`, `If-None-Match: *` where honoured. (3) On 201/204, `PROPFIND Depth: 0` → `getcontentlength == local size` (+ `getetag` persisted if present) → `uploaded`. (4) If a File Station session is linked, `SYNO.FileStation.MD5 start` on the same path and poll `status` until `finished`, compare to the stored MD5 → `verified(md5)`; otherwise `verified(size_only)` plus a sampled full `GET` read-back and SHA-256 compare (first 20 files, then 1 in 20). (5) `MOVE` with `Destination: /<share>/PaperVault/<YYYY>/<final name>` and `Overwrite: F`; on 412 retry with `_01`. The move is after verification so a crash between PUT and MOVE leaves a verified object in `_inbox/` that the next launch sweeps.

**File Station alternative.** Same shape with `SYNO.FileStation.Upload` (multipart body written to a temp file for the background session), `overwrite=false` (v2) so a replay cannot clobber, `SYNO.FileStation.Rename` for the label, `SYNO.FileStation.MD5` for verification. Keep the `sid` in the Keychain, re-login on error 106 or 119, and store `did` so OTP is asked once.

### 2e. Deterministic PDF identity across re-emission

| Rule | Source |
|---|---|
| `/ID` is an array of two byte strings; "The first byte string shall be a permanent identifier based on the contents of the file at the time it was originally created and shall not change when the file is incrementally updated. The second byte string shall be a changing identifier based on the file's contents at the time it was last updated. When a file is first written, both identifiers shall be set to the same value"; "The calculation of the file identifier need not be reproducible" | ISO 32000-1:2008 §14.4, https://opensource.adobe.com/dc-acrobat-sdk-docs/pdfstandards/PDF32000_2008.pdf |
| PDF/A-2/3 rule 6.1.3-1: "The file trailer dictionary shall contain the ID keyword"; 6.6.4: `pdfaid:part`/`conformance` required; extension schemas must be declared | https://github.com/veraPDF/veraPDF-validation-profiles/wiki/PDFA-Parts-2-and-3-rules |
| qpdf: `--deterministic-id` makes the ID "a digest of the significant parts of the content", "a given qpdf operation should generate the same ID each time"; `--static-id` is "for testing only" | https://qpdf.readthedocs.io/en/stable/cli.html |

Protocol for our own writer (the output report already proposes a Swift `ArchivePDFWriter`): `docId` = ULID minted at capture; `pageId_n` = SHA-256 of the normalized page image (dedup report). `/ID[0]` = first 16 bytes of `SHA-256("pap:doc:" + docId)`; `/ID[1]` = first 16 bytes of SHA-256 of the emitted body (computed over everything before the trailer, like qpdf's deterministic mode). `xmpMM:DocumentID` = `uuid:` UUIDv5 of `docId`; `xmpMM:InstanceID` = new UUID per emission; `xmpMM:OriginalDocumentID` = `DocumentID`. `Info /CreationDate` and `xmp:CreateDate` = capture time, never emission time; `/ModDate` and `xmp:ModifyDate` = emission time (PDF/A requires the Info and XMP values to agree). Image XObjects embed the capture-time JPEG bytes stored once under `pageId`; the invisible text layer is replayed from the persisted OCR JSON (never re-run OCR for a re-emission); objects are written in a fixed order with fixed xref formatting. Result: re-emitting the same version yields the same `/ID[1]` and the same file SHA-256, so a replay after a crash is detected as a duplicate by every destination's verification, and a genuine new version differs only in `/ID[1]`, `InstanceID`, `ModDate` and whatever changed.

### 2f. What "immutable after commit" means per destination, and why versioned re-emission is a last resort

If v2 ever re-emits bytes (for example to put the classification inside XMP), each destination supports a same-object update: Drive `PATCH .../upload/drive/v3/files/{id}?uploadType=resumable` (new revision, same id, old revision purgeable after 30 days unless `keepForever`), WebDAV `PUT` over the same path (§9.7 "replaces the GET response entity"), iCloud coordinated `.forReplacing` write. The ledger then holds `(docId, version, sha256)` rows and the rule is "a verified version is never deleted locally until the next version is verified everywhere". But every one of these turns a one-shot durability proof into two, doubles the audit surface, and reintroduces the iCloud conflict case that 2a relied on avoiding. The recommendation is to keep the PDF bytes final at first commit and carry classification elsewhere.

### 2g. Audit: detecting user-side deletion, move, rename after `verified`

| Destination | Mechanism | Detects | Cost |
|---|---|---|---|
| Google Drive | nightly `changes.list(pageToken: stored, includeRemoved: true, fields: changes(fileId,removed,time,file(name,parents,trashed,size,sha256Checksum,version)))`; persist `newStartPageToken`; tokens never expire; quarterly `files.list(q: "'<vault>' in parents", fields: files(id,name,parents,sha256Checksum))` | delete/loss of access (`removed`), trash (`file.trashed`), rename (`name` ≠ ledger), move (`parents` ≠ ledger), overwrite (`sha256Checksum` ≠ ledger, `version` advanced) | 1 call/night typical |
| iCloud Drive | the same long-lived `NSMetadataQuery`: `DidUpdate` userInfo `Removed/Changed/Added` arrays; compare `NSMetadataItemPathKey`, `NSMetadataItemFSSizeKey`, `NSMetadataItemFSContentChangeDateKey` to the ledger; sampled integrity = `startDownloadingUbiquitousItem` → wait for `downloadingStatus == current` → SHA-256 → `evictUbiquitousItem` | delete (removed), rename/move (path change, re-identified by reading XMP `DocumentID` from unknown files), overwrite (size/date change) | free while app runs; nothing while suspended, so reconcile the gather phase at each launch |
| Synology | `PROPFIND Depth: 1` on each year collection (`getcontentlength`, `getlastmodified`, `getetag` if present) or `SYNO.FileStation.List additional=["size","time"]`; sampled `SYNO.FileStation.MD5` | delete (missing), rename (unknown name; re-identify by XMP), overwrite (size/mtime/MD5 change) | one request per year folder, only when reachable |

Remediation policy (same on all destinations): `missing` → re-upload from the local blob (kept until fully replicated + 7 days) or from another verified destination (download, verify SHA-256, upload); `renamed/moved by user` → adopt the user's path in the ledger (their intent wins; the id is in the XMP and, on Drive, in `appProperties`); `overwritten` → do not touch; mark `diverged` and surface once. Deleting on one destination is never propagated to another.

## 3. Options compared

| Question | Option A | Option B (recommended) | Option C |
|---|---|---|---|
| When to upload vs name | Wait for Claude, upload once with the final name (adds classification latency, typically seconds, before the durability tick) | Upload immutable bytes under a provisional name the moment the PDF exists; rename by metadata op when classification lands; late-bind the final name if it arrives before the task is created | Upload original, re-emit enriched PDF as version 2 (storage rec. 1) |
| Copies created | 1 | 1 | 1 object, 2 revisions (Drive keeps old revision 30 days) |
| iCloud conflict exposure | none | none (rename is metadata) | reintroduced |
| Drive calls per doc | 2 (init, PUT) | 3-4 (init, PUT, PATCH, optional get) | 4-5 |
| Verification proofs | 1 | 1 | 2 |
| Durability tick latency | upload + classification | upload only | upload only |

| Destination | Commit op | Verify signal | Rename op | Audit op | Strength |
|---|---|---|---|---|---|
| Google Drive | resumable PUT with pre-generated id | `sha256Checksum` + `size` (server-computed) | `files.update` name / addParents / removeParents | `changes.list` + token | strongest |
| Synology WebDAV (+ File Station MD5) | PUT to `_inbox/` | `getcontentlength` + `SYNO.FileStation.MD5` or sampled read-back | `MOVE` `Overwrite: F` | `PROPFIND Depth: 1` / `List` | strong with MD5, medium with size only |
| iCloud Drive | `setUbiquitous` / coordinated write | `IsUploaded && UploadingError == nil` + size + identity hash | coordinated move + `item(at:didMoveTo:)` | live `NSMetadataQuery` | system assertion, no hash |

## 4. Recommendation for this project

1. **Ledger schema.** `documents(docId, captured_at, sha256_pdf, md5_pdf, size, final_name?, provisional_name)`, `deliveries(docId, dest, state, remote_id, remote_path, session_uri, verify_kind, verify_value, identity_hash, verified_at, named_at, audited_at, last_error)`. States: `pending → staged → uploading → uploaded → verified → named → audited`, with `failed(retry_at)` and `diverged`. Rename failure never regresses `verified`.
2. **Immutable bytes, mutable label.** Build the PDF/A once, with the OCR text layer, before any upload. Provisional name `YYYY-MM-DD_unsorted_unsorted_<id8>.pdf` (capture date) in the capture-year folder; final name `YYYY-MM-DD_<sender>_<doctype>_<id8>.pdf` where the date is the extracted document date when confident. Because most background tasks start after Claude returns (network wait), late-bind the name at task creation and skip the rename entirely when possible.
3. **Classification carriers.** Filename, `<name>.json` sidecar (uploaded as its own small object after the PDF is verified, never blocking the tick), Drive `appProperties {sid, h}` and `contentHints.indexableText`, iCloud Finder tags. Nothing classification-dependent inside the PDF bytes in v1.
4. **Drive.** `drive.file` only; `generateIds` pool of 100; one resumable session per document persisted with its URI; single-PUT background task started in the foreground; `verified` on `sha256Checksum`; 401 → refresh + `*/N` probe + new task; 404 session → new session with the same id; 409 → `files.get` and verify. Publish the OAuth consent screen out of Testing before TestFlight (7-day refresh-token expiry otherwise).
5. **iCloud.** One lifetime `NSMetadataQuery`; `verified` requires `IsUploaded`, no `UploadingError`, size match, and identity hash = current. Freeze the destination on `NSUbiquityIdentityDidChange`; never let rows verified under another token count. Evict local copies only after `verified` and only through `evictUbiquitousItem`.
6. **Synology.** WebDAV over HTTPS with a publicly trusted certificate (DSM Let's Encrypt on `synology.me`, or Tailscale + `tailscale cert`); File Station API session optional but recommended, logged in once with `otp_code` + `enable_device_token=yes` and thereafter with `device_id`; `_inbox/` PUT → size → MD5 job → `MOVE Overwrite: F`. Drop the "trust this fingerprint" prompt; replace it with a certificate-setup guide and a clear "your NAS certificate is not trusted by iOS" error that names the three recipes. Ship static `NSExceptionDomains` CIDR entries for private ranges and `NSAllowsLocalNetworking` for `.local`.
7. **Deterministic emission.** `/ID[0]` and `xmpMM:DocumentID` from `docId`; `/ID[1]`, `InstanceID`, `ModDate` per emission; `CreationDate` = capture time; replay stored JPEG and OCR JSON; fixed object order; gate with veraPDF and a byte-identical re-emission test in CI.
8. **Audit.** Nightly `BGProcessingTask` (network required): Drive changes, Synology PROPFIND per year folder; iCloud reconciliation at each launch's gather phase and continuously while running; 1-in-20 sampled full hash read-back per destination; a quiet "Archive health" screen; remediation = re-upload from blob or a sibling destination, adopt user renames, flag overwrites.
9. **Quorum.** "Captured" tick = 1 `verified` destination (Drive or Synology-with-MD5 preferred over iCloud when several are enabled, because they carry a server-side digest); "fully replicated" = all enabled `verified`; local blob kept until fully replicated + 7 days.

## 5. Risks and unknowns

- Synology 2FA-on-WebDAV, WebDAV ETags, QuickConnect scope and DSM help text could not be read (JS-rendered KB); the DSM Login guide is 2023 and says examples are based on DSM 7.0 — behaviour on DSM 7.2/7.3 is untested here.
- Whether an iCloud rename re-uploads bytes, and how "Recently Deleted" items appear to `NSMetadataQuery`, is undocumented; the protocol tolerates both but the audit may show a transient "missing".
- Google's access-token lifetime is not published; the sample `expires_in: 3920` suggests it is not always 3600. Drive's resumable `PUT` without `Authorization` is undocumented; the design refreshes anyway.
- `evictUbiquitousItem` without an upload check could lose the only copy if `IsUploaded` was read stale; always re-read the key via the query result immediately before evicting.
- A frozen Bearer token in a background task that starts hours later is a guaranteed 401 under the relaunch rate limiter; the retry path must be exercised in tests (airplane mode for > 1 h, then reconnect).
- Tailscale `tailscale cert` files are not auto-renewed on Synology; after 90 days uploads fail with a TLS error, which the app must explain.
- Drive's `sha256Checksum` is "if available"; if it is ever absent, fall back to `md5Checksum`, then to a read-back, and record `verify_kind`.
- File Station multipart bodies must be written to a temp file for background sessions; the `sid` expires (error 106) and must be re-obtained with the stored `did`.

## 6. Open questions for the founder

1. Is a provisional name visible for a few seconds in Drive/Files acceptable, or do you prefer Option A (wait for Claude, upload once) at the cost of a later durability tick?
2. For the tick, is "verified on Google Drive (server SHA-256)" preferred over "uploaded to iCloud (system flag, no hash)" when both are enabled, or should the first to finish count?
3. If you rename or move a file in Drive/Files/DSM yourself, should the app adopt your name (recommended) or restore its own?
4. If a file is overwritten in place by you or another tool, keep your version and flag, or re-upload the archival copy under `_01`?
5. Synology transport: can your NAS get a public certificate today (synology.me DDNS or Tailscale with MagicDNS/HTTPS enabled)? If not, are you willing to install the NAS CA profile on the iPhone?
6. Should classification ever be written into the PDF's XMP (which requires versioned re-emission), or is filename + sidecar + Drive properties enough?
7. Do you want the JSON sidecar next to each PDF in every destination, or only a per-destination `_vault/index.jsonl` manifest?

## 7. Sources

- https://developer.apple.com/documentation/foundation/urlresourcekey/ubiquitousitemisuploadedkey
- https://developer.apple.com/documentation/foundation/urlresourcekey/ubiquitousitemuploadingerrorkey
- https://developer.apple.com/documentation/foundation/nsmetadataubiquitousitemisuploadedkey
- https://developer.apple.com/documentation/foundation/nsmetadataubiquitousitemuploadingerrorkey
- https://developer.apple.com/documentation/foundation/nsmetadataquery
- https://developer.apple.com/documentation/foundation/nsmetadataqueryupdateremoveditemskey
- https://developer.apple.com/documentation/uikit/synchronizing-documents-in-the-icloud-environment
- https://developer.apple.com/documentation/foundation/filemanager/setubiquitous(_:itemat:destinationurl:)
- https://developer.apple.com/documentation/foundation/filemanager/evictubiquitousitem(at:)
- https://developer.apple.com/documentation/foundation/filemanager/ubiquityidentitytoken
- https://developer.apple.com/library/archive/documentation/General/Conceptual/iCloudDesignGuide/Chapters/iCloudFundametals.html
- https://developer.apple.com/documentation/foundation/nsfilecoordinator/coordinate(writingitemat:options:writingitemat:options:error:byaccessor:)
- https://developer.apple.com/documentation/foundation/nsfilecoordinator/writingoptions/formoving
- https://developer.apple.com/documentation/foundation/nsfilecoordinator/item(at:didmoveto:)
- https://developer.apple.com/documentation/foundation/urlubiquitousitemdownloadingstatus
- https://developer.apple.com/documentation/foundation/downloading-files-in-the-background
- https://developer.apple.com/documentation/foundation/urlsessiontask/originalrequest
- https://developer.apple.com/documentation/foundation/urlsessiondelegate/urlsession(_:didreceive:completionhandler:)
- https://developer.apple.com/documentation/security/preventing-insecure-network-connections
- https://developer.apple.com/documentation/bundleresources/information-property-list/nsapptransportsecurity/nsallowslocalnetworking
- https://developers.google.com/workspace/drive/api/guides/manage-uploads
- https://developers.google.com/workspace/drive/api/guides/create-file
- https://developers.google.com/workspace/drive/api/reference/rest/v3/files/generateIds
- https://developers.google.com/workspace/drive/api/reference/rest/v3/files
- https://developers.google.com/workspace/drive/api/reference/rest/v3/files/update
- https://developers.google.com/workspace/drive/api/guides/folder
- https://developers.google.com/workspace/drive/api/guides/manage-changes
- https://developers.google.com/workspace/drive/api/reference/rest/v3/changes/list
- https://developers.google.com/workspace/drive/api/reference/rest/v3/changes
- https://developers.google.com/workspace/drive/api/reference/rest/v3/revisions
- https://developers.google.com/workspace/drive/api/guides/manage-revisions
- https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- https://developers.google.com/workspace/drive/picker/guides/overview
- https://developers.google.com/identity/protocols/oauth2
- https://developers.google.com/identity/protocols/oauth2/native-app
- https://developers.google.com/identity/sign-in/ios/reference/Classes/GIDSignIn
- https://developers.google.com/identity/sign-in/ios/reference/Classes/GIDGoogleUser
- https://developers.google.com/identity/sign-in/ios/reference/Classes/GIDToken
- https://www.rfc-editor.org/rfc/rfc6750.txt
- https://www.rfc-editor.org/rfc/rfc4918.txt
- https://global.download.synology.com/download/Document/Software/DeveloperGuide/Os/DSM/All/enu/DSM_Login_Web_API_Guide_enu.pdf
- https://global.download.synology.com/download/Document/Software/DeveloperGuide/Package/FileStation/All/enu/Synology_File_Station_API_Guide.pdf
- https://tailscale.com/kb/1153/enabling-https
- https://tailscale.com/kb/1131/synology
- https://tailscale.com/kb/1020/install-ios
- https://tailscale.com/kb/1315/mdm-keys
- https://opensource.adobe.com/dc-acrobat-sdk-docs/pdfstandards/PDF32000_2008.pdf
- https://github.com/veraPDF/veraPDF-validation-profiles/wiki/PDFA-Parts-2-and-3-rules
- https://qpdf.readthedocs.io/en/stable/cli.html
