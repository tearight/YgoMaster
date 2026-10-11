# 결정 중계 계약 v1

모든 경로는 숫자 loopback 주소에만 바인딩하며, 설정에 지정한 로컬 32-byte token을 `Authorization: Bearer <token>`으로 받습니다. Jev API 키는 이 경계로 전달하지 않습니다. 본문·응답 제한은 1 MiB입니다. 8개 활성 듀얼과 64개 활성 요청, 최근 256개 종료 기록을 보유합니다.

`pending`은 오래된 요청부터 응답 제한 안에 들어가는 묶음만 반환합니다. 받은 요청을 처리한 뒤 다음 조회에서 나머지를 받습니다. 전체 요청·결정·상태를 포함한 한 기록이 응답 제한을 넘는 경우 `413 record_too_large`로 거절하며, 그 요청이나 상태 변경을 저장하지 않습니다. 새 기록과 상태 변경에는 고정 종료 사유 및 응답 포장을 위한 128-byte 여유를 둡니다.

| 경로 | 역할 |
|---|---|
| POST `/v1/requests` | DLL 클라이언트가 요청 발행 |
| GET `/v1/pending` | 앱이 판단할 요청 목록 조회 |
| GET `/v1/requests/{decisionId}` | 승인·소비·종료 상태 조회 |
| GET `/v1/context/{decisionId}` | 앱 재시작 시 해당 요청 이전의 적용 이력 복구 |
| POST `/v1/decisions` | 앱이 선택한 후보 ID 제출 |
| POST `/v1/acks` | 클라이언트 소비 확인 또는 앱의 실패 반환 |
| POST `/v1/duels/end` | 듀얼 세대 종료 |

요청 필드: `protocolVersion=1`, `duelId`, `duelGeneration`, `decisionId`, `requestSequence`, `actor`, `requestKind`, `rawRequest`, `observation`, `choices`, `constraints`, UTC `deadline`. 새 요청에는 단조 증가하는 sequence가 필요합니다. 새 세대는 이전의 미완료 요청을 취소합니다. 종료된 세대의 지연 결과는 거절합니다.

`observation.chain`은 `order`, `status`(`pending/resolving/resolved`), `sourceLocated`, 공개된 `cardReferences`를 갖습니다. `order`는 ChainSet을 받은 순서이며 native 토큰을 체인 번호로 추측하지 않습니다. 검증된 DLL의 ChainSet/Run/End 패킷은 로컬에서만 대조하고, UID와 위치가 현재 공개 카드 한 장에 일치할 때만 출처를 노출합니다. `chainComplete=false`는 놓친 이벤트나 범위 초과로 체인 추적이 불완전하다는 뜻입니다. 각 출처의 확인 여부는 `sourceLocated`로 따로 표현합니다. 해결이 끝나면 현재 체인을 비우며 최근 공개 이벤트 이력은 유지합니다. 대응 요청은 `selectionContext.role=chain_response`와 마지막 미해결 카드의 `sourceCards`를 제공합니다. 버리기 요청의 causal parent가 확인되지 않으면 null로 두고 적용 이력과 현재 체인을 별도 맥락으로 제공합니다.

후보는 `actionId`, `semanticKind`, `text`, `cardReferences`, `arguments`를 갖습니다. 후보를 실제 setter에 매핑하는 함수는 클라이언트에만 남습니다. 앱·Jev는 메모리 주소나 임의 setter를 반환할 수 없습니다.

제약은 `min`, `max`, `ordered`, `allowEmpty`, `legality`입니다. `single`은 정확히 한 후보, `independent`는 확인된 독립 선택, `allowed_selections`는 명시한 `allowedSelections`만 허용합니다. `unknown`에서는 결과를 받지 않습니다. 생산 DLL decoder는 확인된 Spellbook Organization의 3장 정렬에만 `independent/ordered=true`를 발행하며, 다른 다중 선택은 계속 `unknown`입니다. 이 정렬은 `selectionContext.role=deck_order`, `orderDirection=top_first`와 해결 중인 출처 카드를 제공합니다. 3장 전체의 6개 순서가 Jev의 단일 Choice 후보가 됩니다.

응답 필드: 동일한 `protocolVersion/duelId/duelGeneration/decisionId/actor`, `actionIds`, `provider`, `model`, 선택적 `confidence`. 모델이 보낸 ID·수량·중복·순서를 서버와 엔진 스레드에서 다시 검사합니다. 같은 ID·같은 내용 재전송은 멱등적이며 다른 내용 재사용은 409입니다.

상태는 `pending → accepted → applied`입니다. 취소·거절·기한 초과는 `cancelled/rejected/expired`입니다. `accepted`는 서버가 응답을 검사했다는 뜻입니다. `applied`는 클라이언트가 setter를 실행하고 엔진 요청이 소비됐음을 확인한 뒤에만 반환합니다. 앱의 `rejected`는 소비 확인이 아닙니다.

context 응답은 `protocolVersion/duelId/duelGeneration/actor`, `ended`, `historyLimited=true`, `records`를 갖습니다. 같은 듀얼·세대·actor에서 현재 requestSequence보다 앞선 `applied` 기록만 최신 64개와 1 MiB 안에서 시간순으로 반환합니다. 기록에는 선택한 후보·actionIds·턴·페이즈만 남기고 당시 전체 관측과 다른 후보는 제외합니다. 앱은 새 듀얼 맥락을 만들 때 이 경로를 조회하고, 순서 선택의 이력도 제출한 actionIds 순서로 보존합니다. Jev 상태의 `appliedHistoryLimited=true`는 전체 듀얼 이력이 아니라 보유 중인 최근 이력임을 뜻합니다. 서버의 종료 기록 보유 한도가 함께 적용되며, 서버 자체를 재시작하면 메모리 이력은 사라집니다. 이번 서버와 앱은 함께 갱신해야 합니다.

엔진 호출은 SysAct 스레드에서만 일어납니다. 통신 worker는 복사한 JSON을 보내고 결과를 큐에 넣습니다. queued 결과는 현재 session·actor·marker·deadline을 검사한 뒤 한 번만 적용합니다. 목록 콜백은 56이지만 busy 조회는 55이므로 두 번호를 같은 대기 session에 연결합니다. 단일 목록은 index와 결과 수 1, 다중 목록은 미선택 0·선택 순위 1..n과 결과 수를 사용합니다. 적용 전 정렬 목록의 장수·UID를 다시 확인하고 모든 사전 순위를 지운 뒤 새 순위를 씁니다. 3장 덱 정렬 계약은 정상 초기화한 실제 DLL에서 덱 순서 변경과 다음 드로우까지 검증했습니다.

Jev 요청은 [공식 API](https://docs.typesafe.ai/api)의 `state`와 `questions.action` Choice를 사용하며 초기 모델은 `jev-1.13.0`입니다. criteria는 후보 ID→자연어 문구입니다. 255개 옵션 제한을 지키고, 별도 tokenizer 없이 보수적인 30,000 UTF-8 byte 제한을 둡니다. 이 제한은 Jev의 공식 token 제한과 동일하다는 주장이 아닙니다. 429·529·연결 실패만 기한 내 최대 3회 재시도합니다. 결정은 제출 전에 캐시해 HTTP 응답 손실로 Jev를 다시 호출하지 않습니다.
