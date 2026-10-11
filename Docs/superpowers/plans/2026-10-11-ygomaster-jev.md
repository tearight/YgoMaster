# YgoMaster 외부 Jev AI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** YgoMaster DLL 훅의 입력 요청을 서버와 별도 Jev 앱에 연결하고, 듀얼 맥락과 규칙 기반 자연어 선택지를 통해 받은 결정을 원래 CPU 대신 엔진에 적용한다.

**Architecture:** 클라이언트가 엔진 스레드에서 요청과 관측을 만들고 입력을 보류한다. 서버의 별도 loopback bridge가 요청, 결정, 적용 확인을 중계하며 Python 앱이 맥락을 유지하고 자연어 choices를 구성해 Jev를 호출한다. 기존 DLL 훅과 SysAct 큐를 사용하고, 모델 출력은 후보 식별자로만 받는다.

**Tech Stack:** upstream C#/.NET Framework 4.8, 기존 MiniJSON/HttpListener/Hook, Python 3 표준 라이브러리 unittest/urllib/json, Jev HTTP API.

**Spec:** 같은 폴더의 `ygomaster-jev-design-review.txt` — 2026-10-11 사용자 승인. 실행 시 두 문서를 fork의 `docs/superpowers/specs/2026-10-11-ygomaster-jev.md`, `docs/superpowers/plans/2026-10-11-ygomaster-jev.md`에 옮긴다.

## Global Constraints

- upstream 기준: `0e2078237d46c2450f3a18697b8a756df256b8e9`; MIT 고지 보존.
- GitHub fork: `tearight/YgoMaster`; checkout: `D:\YGOMaster Tools\.local\ygomaster-ai-fork`; 작업 branch: `jev-external-ai`.
- `D:\YGOMaster Solo` 캠페인을 변경하지 않는다. Tools 본체 저장소는 local-only이며 원격 push/외부 공개하지 않는다.
- 별도 fork의 소스와 문서만 공개 저장소 대상으로 삼는다. 키, 게임 인증정보, 저장 데이터, DLL, 추출한 대량 자산은 Git에 넣지 않는다.
- LLM을 써서 선택지 문장을 생성하지 않는다. 선택지를 만드는 코드는 템플릿, 문자열 ID 사전, 현재 관측과 확인된 제약을 사용한다.
- 게임 클라이언트·서버·로그에 Jev API key를 전송하지 않는다. 앱은 `JEV_API_KEY` 환경변수에서만 읽는다.
- DLL getter/setter와 엔진 상태 접근은 엔진 스레드에서 수행한다. 네트워크 대기는 worker에서 수행한다.
- 외부 AI는 명시적으로 켠 Solo 상대 플레이어에만 적용한다. PvP, replay, spectator, 사용자의 플레이어를 구별한다.
- `C2A4F0` 반환 0을 대기로 쓰지 않는다. CPU 함수 구역 전체를 막지 않는다. 알려진 DLL SHA/revision을 검증한 뒤 필요한 내부 상태만 읽는다.
- 합성 메모리, 정상 초기화 DLL 듀얼, 게임 클라이언트, 실제 Jev 호출의 증거를 각각 표시한다. 모의 provider 성공으로 전체 목표를 완료하지 않는다.
- 기존 테스트를 먼저 재사용한다. 구성 요소 계약과 대표 실패를 검사하며 문서 변경 때문에 통과한 검사를 반복하지 않는다.
- 새 주입기, DB, 관리 UI, 클라우드 배포, 별도 패키지 프레임워크를 추가하지 않는다.

## Review Focus

1. **결정 ID 재사용/지연:** 새 듀얼에 이전 응답을 적용하지 않고, 같은 ID의 다른 payload는 거절한다. Task 2의 `DuplicateAndGeneration` 및 Task 5의 `QueuedResultAfterReset`이 소유한다.
2. **콜백 반복/엔진 스레드:** 같은 대기 이벤트가 반복돼도 한 결정만 발행하고, worker가 엔진을 호출하지 않는다. Task 5의 `RepeatedCallbackAndThreadOwnership`이 소유한다.
3. **합법 조합/순서:** 후보 membership와 min/max만으로 특수 합계/소재 선택의 합법성을 주장하지 않는다. Task 4의 `test_combination_requires_legality_evidence`와 Task 6의 실제 다중 선택 검사가 소유한다.
4. **비공개 카드/효과 모호성:** 숨긴 카드의 이름을 노출하거나 카드 전체 설명을 특정 효과로 단정하지 않는다. Task 4의 `test_hidden_identity_and_ambiguous_effect`가 소유한다.
5. **연결 단절/429/종료:** 기한이 지난 요청을 재호출하지 않고, 결과 전송과 실제 적용을 구별한다. Task 3의 `test_retry_stops_on_expiry_or_end`와 Task 7의 프로세스 왕복 검사가 소유한다.

---

## 계약과 파일 배치

기존 `YgoMasterClient.csproj`, `YgoMasterServer/YgoMaster.csproj`는 Compile 항목을 명시한다. 새 공용 C# 파일은 두 프로젝트에서 링크해 같은 계약을 사용한다. 서버 요청 경로의 `x_acts`나 게임 계정 인증은 bridge에 사용하지 않는다.

| 경로 | 책임 |
| --- | --- |
| `ExternalAi/Protocol.cs` | 공용 DTO, JSON 변환, 요청/결정/ack 검증 |
| `ExternalAi/BridgeConfig.cs` | 명시적으로 활성화하는 로컬 통신 설정 |
| `YgoMasterServer/ExternalAi/DecisionStore.cs` | 잠금으로 보호한 요청 수명과 중복 처리 |
| `YgoMasterServer/ExternalAi/DecisionBridge.cs` | 별도 HTTP listener와 짧은 요청 처리 |
| `YgoMasterClient/DuelDll.ExternalAi.cs` | 기존 훅과 연결, hold, 생성/초기화, 큐 적용 |
| `YgoMasterClient/ExternalAi/RequestDecoder.cs` | getter/raw 상태를 입력 후보와 제약으로 변환 |
| `YgoMasterClient/ExternalAi/EngineProfile.cs` | DLL 버전 확인과 필요한 내부 상태 접근 |
| `YgoMasterClient/ExternalAi/BridgeWorker.cs` | 엔진과 분리된 HTTP 전송/결과 확인 |
| `JevApp/jev_app/{__init__,__main__,protocol,bridge,context,choices,metadata,provider,app}.py` | Python 앱과 결정 호출, 자연어 생성 |
| `tests/ExternalAi/{ExternalAi.Tests.csproj,Program.cs,*Tests.cs}` | 의존성 없는 C# 검증 실행 파일 |
| `JevApp/tests/{test_protocol,test_app,test_choices,test_metadata,test_integration}.py` | 표준 unittest |
| `tests/ExternalAi/fixtures/*.json` | 카드 자산을 포함하지 않는 작은 계약 fixture |
| `tools/external-ai/{init-config.ps1,build-tests.ps1,run-dll-scenarios.py}` | 로컬 설정 준비, 기존 빌드 도구 호출 및 독립 DLL 실험 |
| `docs/external-ai/{protocol,runbook,coverage}.md` | 실행·인터페이스·검증 범위 기록 |

### protocolVersion 1

- 요청 필수 필드: `protocolVersion=1`, `duelId`, `duelGeneration`, `decisionId`, `requestSequence`, `actor`, `requestKind`, `rawRequest`, `observation`, `choices`, `constraints`, `deadline`.
- `duelId`는 새 듀얼 GUID, generation/sequence는 양의 정수, actor는 0 또는 1. `deadline`은 UTC ISO 8601이다. 클라이언트가 값을 발행하고 서버가 보관한다.
- 후보 필드: `actionId`, `semanticKind`, `text`, `cardReferences`, `arguments`. `arguments`는 이름/위치/개수처럼 문장 구성에 필요한 값이며 메모리 주소나 setter 호출 코드가 아니다.
- 클라이언트 내부 map: `actionId -> EngineAction`. 명령 enum, 위치/index, dialog 값, list index/rank는 이 map에만 보관한다. 앱이 명령 mask를 command ID로 반환할 수 없다.
- `observation`: 현재 turn/phase/LP, 관측 가능한 카드와 공개 이벤트 이력, 현재 효과/코스트/대상 관계. 불명확한 `parentDecisionId`/effect 관계는 null로 남긴다.
- `constraints`: `min`, `max`, `ordered`, `allowEmpty`, `legality`와 확인된 `allowedSelections` 또는 검증에 필요한 rule data. 증거가 없는 조합은 `legality="unknown"`이다.
- 요청 해석 상태는 `rawRequest.decodeStatus`의 `complete`/`unsupported`와 `reason`에 남긴다. 미해석 값을 정확한 자연어인 것처럼 제출하지 않는다.
- 결과: 요청 identity + `actor`, `actionIds`(단일 선택도 배열), `provider`, `model`, 선택적 `confidence`. 서버는 후보 membership, 중복, 순서/수량, 기한, generation을 확인한다.
- 상태: `pending -> accepted -> applied`; 또는 `rejected/cancelled/expired`. `accepted`는 결정 수신, `applied`는 엔진이 입력을 소비한 확인이다. 결정 수신만으로 applied를 보내지 않는다.

### HTTP bridge

별도 prefix `http://127.0.0.1:49172/`가 기본값이다. config의 `enabled=false`가 기본이고 `tokenFile`이 가리키는 로컬 파일의 32-byte 난수 token을 `Authorization: Bearer`로 사용한다. 예제 config에는 token 값을 넣지 않는다. 서버/클라이언트가 token을 생성하거나 바꾸는 경쟁을 피하도록 준비 도구에서 한 번 생성한다.

| 요청 | 의미 |
| --- | --- |
| `POST /v1/requests` | 클라이언트가 결정 발행; 동일 canonical payload 재전송은 동일 record |
| `GET /v1/pending` | 앱이 아직 pending인 요청 조회; 장기 대기 없음 |
| `POST /v1/decisions` | 앱이 선택 반환; accepted 상태 반환 |
| `GET /v1/requests/{decisionId}` | 클라이언트/앱이 요청 및 결정/ack 상태 조회 |
| `POST /v1/acks` | 클라이언트가 적용/거절/취소 사유 반환 |
| `POST /v1/duels/end` | 같은 duelId/generation의 요청 취소 |

초기 상한: body 1 MiB, 활성 듀얼 8, 미완료 요청 64, 완료 record 256(오래된 것부터 제거), 공개 이벤트 64. payload를 조용히 잘라서 정상 요청처럼 취급하지 않는다. 기본 요청 기한 120초, 개별 HTTP timeout 5초, worker polling 250ms. 기한/상한은 검증된 config에서 조절 가능하다. 잘못된 인증 401, 잘못된 JSON/계약 400, identity 충돌/상태 충돌 409, 과대 body 413, 수용량 초과 429이다.

## Task 1: 독립 fork와 빌드 기준 확보

**Files:** fork의 두 프로젝트 및 `.gitignore`(로컬 secret/출력 제외); 승인된 spec/plan 문서 복사. 기존 제품 소스는 이 작업에서 변경하지 않는다.

**Interfaces:** 다음 task의 작업 root와 확인된 C# 빌드 실행 경로를 제공한다. 테스트 출력 경로는 `tests/ExternalAi/bin/x64/Debug/ExternalAi.Tests.exe`로 고정한다.

- [ ] **Step 1:** `gh repo view tearight/YgoMaster`와 upstream SHA, checkout 대상 부재/기존 소유를 확인한다. 존재하면 올바른 fork인지 확인하고 재사용하며 덮어쓰지 않는다.
- [ ] **Step 2:** `gh repo fork pixeltris/YgoMaster --clone=false`로 요청된 GitHub fork를 생성하고 명시한 경로에 clone한다. `jev-external-ai` branch를 기준 SHA에서 만든다. clone 내부의 AGENTS 및 적용되는 부모 지침을 확인한다.
- [ ] **Step 3:** 승인 spec/plan을 위 docs 경로에 저장하고 `.gitignore`에 bridge token/config, Python cache와 검증 출력 경로를 넣는다. 소스 fork만 Tools 관리 아래 두고 Solo/Tools 본체에 제품 의존성을 추가하지 않는다.
- [ ] **Step 4:** Windows Framework MSBuild로 upstream `YgoMaster.sln /p:Configuration=Debug /p:Platform=x64`를 빌드한다. 실제 프로젝트가 요구하는 targeting pack/기존 참조를 확인해 실패 원인별 최소 수정만 수행한다. C++ loader를 다시 만드는 것은 이 C# 변경에 필요할 때만 수행한다.
- [ ] **Step 5:** 빌드 로그와 baseline SHA를 local 출력에 기록하고 승인 문서/ignore 변경만 commit한다. 기존 SDK 부재 자체를 빌드 불가능으로 판정하지 않는다.

**통과 증거:** fork origin/upstream, branch 기준 SHA, client/server C# 성공 출력. 서버·게임을 실행하거나 설치 파일을 복사한 결과로 대체하지 않는다.

## Task 2: 공용 계약과 서버 결정 중계

**Files:** `ExternalAi/Protocol.cs`, `ExternalAi/BridgeConfig.cs`, `YgoMasterServer/ExternalAi/{DecisionStore,DecisionBridge}.cs`, `YgoMasterServer/{Program,GameServer}.cs`, 두 csproj, C# 테스트 프로젝트와 `ProtocolTests.cs`, `DecisionStoreTests.cs`, `BridgeTests.cs`; fixtures `single-request.json`, `ordered-list-request.json`; `tools/external-ai/{init-config,build-tests}.ps1`.

**Interfaces (namespace `YgoMaster.ExternalAi`):**

- static `ExternalAiProtocol`: `DecisionRequest ParseRequest(string json, DateTime utcNow)` / `DecisionResponse ParseDecision(string json)` / `Dictionary<string,object> ToDictionary(DecisionRequest request)`.
- `ExternalAiProtocol.ValidateDecision(DecisionRequest request, DecisionResponse response, DateTime utcNow) -> string` — null이면 유효, 아니면 고정된 reason code.
- C# DTO 속성은 JSON 필드의 PascalCase 이름을 사용한다. `DecisionRecord.Request: DecisionRequest`, `Response: DecisionResponse`, `State: string`, `Reason: string`. 검사 예외는 `ProtocolException.Reason: string`, `StatusCode: int`; 테스트 runner helper는 `Check(bool condition, string message)`와 `Rejects(Action operation, int statusCode)`이다.
- `BridgeConfig Load(string path)` — enabled/prefix/tokenFile/deadline/limits; 비 loopback prefix와 누락 token 거절.
- `tools/external-ai/init-config.ps1 -OutputDirectory <local-dir>`는 `ExternalAi.local.json`과 `external-ai.token`을 생성한다. 기존 token/config는 덮어쓰지 않으며 파일 경로만 출력한다. client/server/app이 같은 파일을 읽는다.
- `DecisionRecord DecisionStore.Publish(DecisionRequest request, DateTime now)`; `IList<DecisionRecord> Pending(DateTime now)`; `DecisionRecord Submit(DecisionResponse response, DateTime now)`; `DecisionRecord Get(string decisionId, DateTime now)`; `DecisionRecord Acknowledge(DecisionAck ack, DateTime now)`; `void EndDuel(string duelId, long generation, DateTime now)`.
- `DecisionBridge(BridgeConfig config, DecisionStore store)`, `void Start()`, `void Dispose()`; store는 같은 lock 안에서 상태 전환, JSON fingerprint는 key 순서와 무관하게 계산.
- normal 서버의 명시적 config 활성화와 `--external-ai-bridge-only --external-ai-config <path>` 모드를 제공한다. bridge-only는 게임 데이터/account/load settings를 요구하지 않는다.

- [ ] **Step 1: 실패 검사 작성.** `ProtocolAndLimits`는 version≠1/actor=2/없는 actionId/중복 선택/기한 만료를 거절한다. `DuplicateAndGeneration`은 같은 요청 재발행 시 record 하나, 다른 payload 같은 ID는409, end/new generation 뒤 이전 응답 거절을 확인한다. `AcceptedIsNotApplied`는 submit 뒤 accepted이며 ack 전 applied가 아님을 확인한다.

```csharp
Check(store.Publish(request, now).State == "pending", "new request");
store.Publish(request, now); // 동일 fixture 재전송
Check(store.Pending(now).Count == 1, "idempotent publish");
Check(store.Submit(response, now).State == "accepted", "not applied yet");
Check(store.Get(request.DecisionId, now).State != "applied", "wait for engine ack");
store.EndDuel(request.DuelId, request.DuelGeneration, now);
Rejects(() => store.Submit(response, now), 409);
```
- [ ] **Step 2:** `tools/external-ai/build-tests.ps1`을 만들어 기존 Framework MSBuild로 테스트 runner를 빌드·실행한다. 먼저 미구현 계약 때문에 실패함을 확인한다. runner는 테스트 이름과 PASS/FAIL, 실패 시 nonzero를 출력한다.
- [ ] **Step 3:** 위 DTO/변환/validation/store 인터페이스를 구현한다. 처음부터 schema 의미를 공용 테스트 fixture로 고정하고 endpoint에서 body/용량/인증을 검사한다. record는 immutable 요청과 결정 복사본을 보관한다.
- [ ] **Step 3a:** `init-config.ps1`로 .NET RandomNumberGenerator의 32-byte 난수를 Base64 token으로 저장한다. 새 디렉터리 생성 및 기존 파일 보존을 한 번 확인한다. 실제 token은 테스트 fixture나 commit에 넣지 않는다.
- [ ] **Step 4:** 별도 listener와 thread를 구현하고 종료 시 listener를 닫는다. HTTP 핸들러는 Jev·엔진·장기 poll을 호출하지 않는다. `Program.Main`과 `GameServer.Start`에 config 활성화 연결을 추가한다. 기본 비활성에서 기존 서버 경로를 보존한다.
- [ ] **Step 5:** `BridgeHttpContract`에서 실제 listener에 401/413/409와 정상 request→decision→ack를 보내 확인한다. `GET pending` 처리 중 기존 게임 요청 루프를 점유하지 않는 구조를 검사한다. URL ACL 문제가 실제로 발생하면 필요한 로컬 바인딩 조치만 기록하고 전역 시스템 설정을 임의로 바꾸지 않는다.
- [ ] **Step 6:** `& tools/external-ai/build-tests.ps1 -Suite Server`와 C# 두 프로젝트 빌드 성공 후 이 task 파일만 commit한다.

## Task 3: 별도 Python 앱, 맥락 상태머신과 Jev provider

**Files:** `JevApp/jev_app/{__init__,__main__,protocol,bridge,context,provider,app}.py`, `JevApp/tests/{test_protocol,test_app}.py`, `docs/external-ai/protocol.md`.

**Interfaces:**

- `validate_request(data: dict, now: datetime) -> dict`, `validate_decision(request: dict, result: dict, now: datetime) -> dict` — Task 2 fixture/계약을 사용한다.
- `BridgeClient.publish_decision(result: dict) -> dict`, `pending() -> list[dict]`, `get(decision_id: str) -> dict` — Authorization token은 파일에서 읽고 출력하지 않는다.
- `DuelContext.update(request: dict) -> dict`, `acknowledge(record: dict) -> None`, `end(duel_id: str, generation: int) -> None` — 공개 이력과 현재 관계를 유지하며 입력 적용은 ack 후 기록한다.
- `DecisionProvider.choose(state: dict, criteria: dict[str,str], deadline: datetime) -> ProviderChoice`.
- `JevProvider`는 `POST https://api.typesafe.ai/v1/systemone`, `model="jev-1.13.0"`, `state`, `questions={"action":{"type":"choice","instructions":"현재 듀얼 상태와 선택 맥락을 바탕으로 승리에 가장 도움이 되는 합법적인 행동을 선택한다.","criteria":...}}`를 보낸다. `Authorization: Bearer <API_KEY>`를 사용하고 `answers.action.choice`를 읽는다. 2026-10-11 공식 `https://docs.typesafe.ai/api`와 대조했다.
- `ProviderChoice`는 `choice`, `provider`, `model`, `confidence`; `MockProvider`는 모의임을 표시한다.
- `DecisionApp.step(now: datetime) -> None`, `run() -> int`; CLI `python -m jev_app --bridge-config <path> --provider mock|jev`.
- 상태 enum: `waiting`, `received`, `building`, `choosing`, `validated`, `submitted`, `awaiting_applied`, `done`, `cancelled`, `expired`, `failed`. provider 호출 중 새 duel/generation이나 종료를 확인하면 결과를 제출하지 않는다.

- [ ] **Step 1: 실패 검사 작성.** `test_context_follows_ack_not_submission`은 submitted가 행동 완료 이력에 들어가지 않음을 확인한다. `test_reconnect_keeps_request_identity`는 같은 pending을 재조회해 새 ID/가짜 parent를 만들지 않음을 확인한다. `test_retry_stops_on_expiry_or_end`는 429/529 뒤 요청 종료 시 호출·전송0회를 확인한다.

provider/transport test double의 기록을 다음처럼 확인한다. provider는 첫 시도 429, bridge는 다음 조회에서 expired를 반환한다.

```python
self.assertEqual(fake_provider.call_count, 1)
self.assertEqual(fake_bridge.submitted, [])
self.assertEqual(app.states[request["decisionId"]], "expired")
self.assertNotIn(api_key, captured_trace)
self.assertNotIn(bridge_token, captured_trace)
```

`DecisionApp.states`는 decisionId→상태 문자열 map이며 테스트 double의 call_count/submitted는 제품 API가 아니다.
- [ ] **Step 2:** `py -3 -m unittest discover -s JevApp/tests -p test_app.py -v`를 실행해 앱 미구현으로 실패함을 확인한다. provider, clock, transport는 테스트에서 주입해 실제 sleep/API 요금 없이 경계를 검사한다.
- [ ] **Step 3:** 위 protocol/client/context/app 인터페이스를 구현한다. 동일 request 처리 상태를 추적하고 재연결 시 서버 record와 대조한다. 맥락 복원이 불가능하면 snapshot/확인된 이력만 사용하며 관계는 unknown으로 표시한다.
- [ ] **Step 4:** mock/실제 provider를 구현한다. Choice255개 상한, 응답 choice membership, finite confidence, response size를 검사한다. 401/422는 즉시 failed, 429/529/일시 연결 실패는 1·2·4초 최대3회 재시도하되 매번 bridge 상태/기한 확인 후 진행한다. key/Authorization/raw credential은 오류 로그에서도 제거한다.
- [ ] **Step 5:** `test_jev_envelope_and_invalid_choice`로 로컬 fake HTTP 서비스에 실제 urllib 요청을 보내 envelope와 잘못된 choice 거절을 확인한다. `test_no_secret_in_trace`로 trace에 API key/bridge token이 없음을 확인한다.
- [ ] **Step 6:** 해당 Python 검사 통과 후 실제 component protocol 문서와 task 파일만 commit한다. API key가 없어도 mock 및 로컬 fake HTTP 검증을 완료하며 실제 Jev 성공을 주장하지 않는다.

## Task 4: 글로벌 상태와 문자열 사전으로 자연어 choices 구성

**Files:** `JevApp/jev_app/{choices,metadata}.py`, `JevApp/tests/{test_choices,test_metadata}.py`, 작은 자체 작성 fixture `metadata-offsets.json`, `choice-cases.json`, `docs/external-ai/coverage.md`.

**Interfaces:**

- `CardCatalog.from_files(index_path: Path, name_path: Path, desc_path: Path, prop_path: Path) -> CardCatalog` — upstream `YdkHelper.LoadCardDataFromGame`의 카드ID 계약을 동일하게 구현한다.
- `TextCatalog.from_files(index_path: Path, text_path: Path) -> TextCatalog`, `resolve(group: str, string_id: int) -> str | None` — DLG/WORD 실제 index/text 계약을 읽기 전용으로 확인한 후 고정한다. 확인되지 않은 ID는 None을 반환한다.
- `render_choice(choice: dict, request: dict, cards: CardCatalog, texts: TextCatalog) -> str`.
- `build_question(request: dict, context: dict, cards: CardCatalog, texts: TextCatalog) -> ChoiceQuestion`.
- `ChoiceQuestion.criteria: dict[str,str]`, `ChoiceQuestion.selections: dict[str,list[str]]`; provider choice key를 selections를 통해 원래 actionIds로 돌린다. 단일 후보 key는 actionId를 그대로 사용한다.
- 메뉴 명령/체인 yes-no/dialog 문자열/카드 위치/순서/개수/숫자/속성/종족/위치 선언용 문장 틀을 제공한다. 예: `자신 필드의 [카드명] 효과를 발동한다`, `대상을 선택한다: 상대 필드의 공개된 [카드명]`, `이 효과를 발동하지 않는다`. 효과별 상세 문구는 해당 ID/효과 참조를 확인한 경우만 붙인다.

- [ ] **Step 1: 실패 검사 작성.** `test_menu_templates_keep_instance_identity`는 같은 카드ID의 서로 다른 UID/위치가 다른 actionId와 문장을 갖는지 확인한다. `test_hidden_identity_and_ambiguous_effect`는 숨긴 카드명의 미노출과 다중 효과의 미확정 상세 문구 제외를 확인한다. `test_combination_requires_legality_evidence`는 min/max만 있는 복합 선택을 unsupported로 판정하고 검증된 ordered 조합의 순서를 보존한다.

```python
self.assertNotIn("비공개카드테스트명", render_choice(hidden, request, cards, texts))
self.assertNotEqual(render_choice(first, request, cards, texts),
                    render_choice(second, request, cards, texts))
request["constraints"]["legality"] = "unknown"
with self.assertRaisesRegex(ValueError, "unknown_legality"):
    build_question(request, context, cards, texts)
request["constraints"]["legality"] = "allowed_selections"
request["constraints"]["allowedSelections"] = [["card_b", "card_a"]]
question = build_question(request, context, cards, texts)
self.assertEqual(list(question.selections.values()), [["card_b", "card_a"]])
```
- [ ] **Step 2:** `py -3 -m unittest discover -s JevApp/tests -p test_choices.py -v` 실패를 확인한다.
- [ ] **Step 3:** card/text parser를 구현한다. offset 범위, UTF-8/NUL, 누락 ID, 손상 데이터에 명확한 오류를 반환한다. 테스트는 게임 원문을 복제하지 않는 소형 자체 bytes fixture를 쓴다. 실제 데이터와의 대조 결과만 local 증거에 남긴다.
- [ ] **Step 4:** renderer와 ChoiceQuestion을 구현한다. 카드ID만으로 선택 문맥을 추정하지 않고 request actor/locate/face/semanticKind와 context를 사용한다. 전체 조합은 확인된 allowedSelections/rule 검증에서만 생성한다. 255개를 넘으면 합법적으로 분해할 수 있는 요청만 단계화하며 조용히 후보를 버리지 않는다.
- [ ] **Step 5:** `test_sparse_dialog_slots`에서 sparse packed slot을 연속 index로 바꾸지 않음을 확인한다. `test_unknown_label_is_explicit`와 `test_option_limit_is_not_truncation`에서 미해석/과대 요청을 정확히 보고한다. metadata tests에서 cardID↔offset과 DLG/WORD namespace 충돌을 확인한다.
- [ ] **Step 6:** choice/metadata 테스트 통과 후 task 파일과 coverage 문서를 commit한다. 미해석 문자열/선택 유형은 coverage에 engine 입력 계약, 자연어 해석, 실제 소비 검증을 각각 기록한다.

## Task 5: DLL 입력 보류와 engine thread 적용

**Files:** `YgoMasterClient/DuelDll.ExternalAi.cs`, `YgoMasterClient/ExternalAi/{RequestDecoder,EngineProfile,BridgeWorker}.cs`, `YgoMasterClient/{DuelDll,DuelDll.ProxyFunctions,ClientSettings}.cs`, `YgoMasterClient.csproj`, `tests/ExternalAi/{DecoderTests,InputControllerTests}.cs`.

**Interfaces:**

- partial `DuelDll`: `ExternalAiOnRunEffect(int id, int p1, int p2, int p3)`, `bool ExternalAiIsBusy(int effectId)`, `ExternalAiBeforeSysAct()`, `ExternalAiAfterSysAct(int result)`, `ExternalAiReset()`.
- `int ExternalAiPlayerType(int player, int requestedType)` returns0(Human) only for configured Solo CPU target1; all other inputs retain requested type. Enable requires verified Solo mode, actor scope and EngineProfile support.
- `RequestDecoder.Decode(EngineSnapshot snapshot, RawEffect effect) -> DecodedRequest`; `DecodedRequest` includes DecisionRequest and `Dictionary<string,EngineAction> Actions`. These DTOs remain in the client module; private native getters are wrapped in the partial DuelDll adapter.
- `EngineProfile.TryOpen(IntPtr module, string path, out EngineProfile profile) -> bool`; actor/menu/dialog/list readers validate work base/ranges and pinned DLL SHA/revision before reading required offsets. Unknown versions disable external AI and report reason, never guess offsets.
- `BridgeWorker.Enqueue(DecisionRequest request)`, `TryTakeResult(out DecisionResponse response)`, `EnqueueAck(DecisionAck ack)`, `Cancel(string duelId, long generation)`; worker only handles serialized/copy data.
- `EngineAction.Apply()` dispatches original existing native setters on engine thread. Validation rechecks active identity/actor/candidate map before enqueue and immediately before apply.
- `ClientSettings.ExternalAiConfigPath` selects BridgeConfig; empty means disabled. actual current duel mode, MyID/RivalID, replay/spectator status determine ownership. Settings reload during active request cancels that request.

- [ ] **Step 1: 실패 검사 작성.** `RepeatedCallbackAndThreadOwnership`는 반복 callback이 한 decisionId만 발행하고 worker getter/setter 호출0회임을 확인한다. `QueuedResultAfterReset`은 SysAct 큐에 있던 이전 generation 결과가 setter0회/거절 ack임을 확인한다. `CpuScopeAndBusyPreservation`는 target CPU만 Human으로 변환하며 다른 플레이어/PvP/replay는 보존하고 원래 busy가1이면 계속 busy임을 확인한다.

최소 test adapter는 emitted request, 엔진 호출 thread ID와 setter 횟수를 기록한다. 반복 callback 뒤와 reset 뒤 각각 확인한다.

```csharp
Check(fakeBridge.Published.Count == 1, "one decision for repeated callback");
Check(fakeEngine.WorkerCalls == 0, "native access stays on engine thread");
Check(fakeEngine.SetterCalls == 0, "stale queued result after reset");
Check(fakeBridge.LastAck.State == "rejected", "stale result rejected");
```
- [ ] **Step 2:** native 함수 대신 주입한 최소 engine adapter를 사용하는 controller/decoder 테스트가 실패함을 확인한다. 기존 Hook/큐를 복제한 다른 runtime을 제품에 추가하지 않는다.
- [ ] **Step 3:** EngineProfile과 decoder를 구현한다. WaitInput menu는 Main+3CD0, actor는 Main+3D00; dialog actor+3C98/request+3C94; list pointer는 확인된 work+3DD0로 구분한다. 메뉴 actor에 RecommendSide를 범용 getter로 쓰지 않는다. DLL 카드 text stub 대신 앱 metadata를 사용한다.
- [ ] **Step 4:** player type 훅, RunEffect, IsBusyEffect, ClearState/duel init, SysAct 전후에 partial 함수 호출을 연결한다. hold를 원래 callback 전에 설정해 phase default result 조기 소비를 막는다. 원래 표시 callback/busy를 보존하고 외부 소유 입력의 자동 UI setter가 경합하지 않도록 기존 입력 훅에서 소유 검사한다. UI 소유가 아직 미검증이면 활성화를 제한하고 Task 6에서 해결한다.
- [ ] **Step 5:** 네트워크 worker와 SysAct 큐를 연결한다. 큐의 lock 안에서는 복사만 하고 실행은 엔진 스레드에서 한다. 명령은 mask→enum 명시 매핑, dialog는 원래 slot/값, list는 0부터 연속 rank와 count로 적용한다. setter 실행 후 SysAct/요청 전환에서 실제 소비를 확인해 applied ack를 보낸다. 소비가 확인되지 않으면 accepted를 유지한다.
- [ ] **Step 6:** `& tools/external-ai/build-tests.ps1 -Suite Client`와 실제 client C# 빌드, 기존 server/app contract 검사 중 변경 영향이 있는 것만 실행한다. task 파일 commit. 합성 engine adapter 검사와 실제 DLL 검사를 구별한다.

## Task 6: 정상 초기화 DLL에서 입력·CPU 우회 계약 확인

**Files:** `tools/external-ai/run-dll-scenarios.py`, `tests/ExternalAi/fixtures/dll-scenarios.json`, 필요한 RequestDecoder/EngineProfile 수정, `docs/external-ai/coverage.md`.

**Interfaces:** CLI `py -3 tools/external-ai/run-dll-scenarios.py --dll <explicit-path> --data <local-content-path> --output <local-output-dir>`. 자식 프로세스마다 DLL을 정상 초기화하고 종료한다. loader/injector를 새로 만들지 않고 기존 DuelSimulator의 InitContent/초기화/export 계약을 참고한다. 데이터 경로를 찾으려고 Solo 저장 파일을 스캔하지 않는다.

- [ ] **Step 1:** 기존 연구 probe/fixtures와 정상 초기화 경로를 대조해 현재 version의 main/battle/check timing/chain, yes-no/effect/phase, 단일·다중 list, sort, 숫자·속성·종족·위치 선언을 coverage에 등록한다. 각 항목은 요청 actor, 후보 원본, natural label, setter contract, consumed 증거 칸을 갖는다.
- [ ] **Step 2:** 정상 초기화 요청 scenario의 기대 actor/action/value를 작은 fixture로 작성하고 현재 adapter가 실제 입력을 소비하지 못하는 항목을 실패로 관측한다. 예전 synthetic work memory probe 성공을 이 단계 성공으로 계산하지 않는다.
- [ ] **Step 3:** 독립 host를 구현해 카드 데이터/deck init, effect/busy delegate, SysAct, 공개 이벤트 및 native 입력의 왕복을 기록한다. DLL hash/revision과 event sequence/CPU evaluator 진입 횟수/결정 identity를 남긴다. getter의 전역 상태는 해당 callback에서 읽은 복사본으로 후보를 만든다.
- [ ] **Step 4:** 대표 main→effect→target 또는 chain→cost→target 경로, 두 장 ordered/unordered list, phase default override를 수행한다. 요청당 한 결과만 적용되고 원래 CPU evaluator가 실행되지 않으며 정상 후속 effect/요청으로 진행하는 것을 확인한다. auto-fill/무효 index 보정이 성공으로 오인되지 않게 실제 선택 UID/rank를 대조한다.
- [ ] **Step 5:** 필요한 decoder/actor/privacy/hold 경계만 수정하고 해당 실패 scenario를 재실행한다. 특수 합계/소재/선언은 실제 제약 증거를 확보해서 입력한다. 미해석 항목은 임의 값으로 통과시키지 않고 명시적 unsupported와 남은 작업으로 기록한다.
- [ ] **Step 6:** 정상 초기화가 불가능한 원인이 데이터/도구 접근인지 engine contract인지 분리해 기록한다. 가능한 소스·통신·렌더링 작업은 계속한다. 성공한 항목의 로그/짧은 재현 방법과 수정 파일을 commit하되 게임 assets/log 원문은 local에만 둔다.

**완료 판단:** 이 task의 대표 실제 경로에 consumed/CPU bypass 증거가 없으면 목표 전체를 완료로 표시하지 않는다. 실제 UI 소유 경합은 독립 host로 입증할 수 없으므로 Task 7에서 따로 확인한다.

## Task 7: 구성 요소 왕복, 실제 Jev와 Solo 실행 검토

**Files:** `JevApp/tests/test_integration.py`, `docs/external-ai/{runbook,coverage}.md`, 필요 최소 수정, local 실행 증거.

**Interfaces:** Task 2 bridge-only 실행 모드, Task 3 app CLI, Task 5 동일 envelope/engine action, Task 6 DLL host를 사용한다. 실행 결과에 provider 종류와 실제 검증 환경을 필수 기록한다.

- [ ] **Step 1: 실패 검사 작성.** `test_process_round_trip_and_delayed_response`는 실제 C# bridge 프로세스와 Python 앱 프로세스로 request→accepted→engine ack→applied를 확인한다. duplicate/late response/end/new generation을 대표 한 번씩 보내 setter가 재적용되지 않음을 확인한다. trace는 비밀을 포함하지 않는다.

```python
self.assertEqual(before_ack["state"], "accepted")
self.assertEqual(after_ack["state"], "applied")
self.assertEqual(fake_client.setter_count, 1)
self.assertEqual(late_response.status, 409)
self.assertNotIn(bridge_token, process_trace)
```
- [ ] **Step 2:** `py -3 -m unittest discover -s JevApp/tests -p test_integration.py -v`를 실행해 구성 요소 연결 실패를 확인한 뒤 필요한 계약/수명 수정만 적용한다. native engine 대신 fake client를 쓴 검사와 native host를 쓴 검사의 이름/결과를 구별한다.
- [ ] **Step 3:** 모든 변경과 관련된 C# 빌드/단위/프로세스/native 대표 검사를 한 번 실행하고 결과를 coverage/runbook에 연결한다. component 통신 성공이면 정상 동작으로 기록하지만 실제 Jev/DLL/UI 미확인을 숨기지 않는다.
- [ ] **Step 4:** 앱에 `JEV_API_KEY`가 제공된 경우 실제 Jev로 최소 한 실제 요청을 처리하고 선택 후보→서버→native 입력 소비까지 대조한다. 키가 없으면 키가 필요한 단계만 구체적으로 알리고 나머지 검증과 review 가능한 실행물을 완성한다. 인증정보는 사용자에게 채팅으로 붙여넣도록 요구하지 않는다.
- [ ] **Step 5:** Solo 통합을 위해 변경 파일, 실행 경로, 활성화 config, 대상 플레이어, rollback, 관측 항목을 준비한다. 사용자가 승인한 별도 실행 환경에서 기존 DLL loader를 재사용하며 실제 UI 자동 입력 경합·callback 보존·외부 CPU 요청의 소비를 관찰한다. 기존 캠페인/설치/저장 파일에 배포가 필요하면 그 정확한 변경안을 마지막에 검토받는다.
- [ ] **Step 6:** 실제 효과/chain/다중 선택/지연/듀얼 종료 결과를 반영하고 관련 파일을 commit한다. 계획에서 선택한 실행 방법에 따른 fresh 전체 branch review를 수행해 actionable 결함을 수정한다. 기본 fork creation 외에 branch 공개/push/PR은 사용자의 기존 공개 의도와 local-only 지침을 다시 대조해 수행한다.

**전체 완료 조건:** fork와 실제 build, 통신 round trip, 맥락 있는 자연어 후보, 원래 CPU 우회, native 실제 입력 소비, 실제 Jev 호출, 대표 Solo UI 경로의 증거가 갖춰져야 한다. 알려진 미지원 경로/제약과 각 검증 범위는 함께 보고한다. 미완료·키 필요·실행 환경 필요는 목표를 축소하는 이유가 아니다.

## 계획 자체 검토 — 2026-10-11

- 승인 spec의 client/server/app/자연어/보안·수명/실제 검증 요구를 Tasks 1–7에 배정했다. 외부 서버만 구현해서 CPU 제어가 된다는 가정을 제거했다.
- 구현 함수와 소비 인터페이스 이름을 맞췄다. 응답의 단일 선택도 actionIds로 통일하고 제v 내부 조합 key를 engine actionId와 혼동하지 않게 했다.
- 5개 Review Focus마다 소유 task/검사를 지정했다. upstream 빌드 기준, decoder 증거, 실제 UI 경합을 서로 다른 검증 단계로 둔다.
- 글로벌 메모리 읽기는 DLL profile gate와 engine-thread snapshot에 한정한다. 자연어 생성은 별도 앱에서 수행하므로 메모리를 직접 참조하는 앱을 요구하지 않는다.
- 실제로 확인할 사항은 DLG/WORD ID 대응, 정상 초기화 자료 경로, Human player type의 실제 UI 동작이다. 각각 Tasks 4/6/7의 증거 확보 항목으로 남겼고 임의 가정으로 통과시키지 않는다.
- 새 하위 프레임워크/DB/UI 없이 기존 C#·Python stdlib를 사용한다. setup/documentation은 해당 기능 task에 포함한다.
- 이 문서는 구현 계획 검토안이다. fork 생성이나 제품 코드 변경은 아직 하지 않았다. 작성된 설계의 승인은 이미 받았으며 다음 승인 대상은 이 계획과 실행 방법뿐이다.
