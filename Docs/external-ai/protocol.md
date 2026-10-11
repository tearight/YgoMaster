# 결정 중계 계약 v1

모든 경로는 숫자 loopback 주소에만 바인딩하며, 설정에 지정한 로컬 32-byte token을 `Authorization: Bearer <token>`으로 받습니다. Jev API 키는 이 경계로 전달하지 않습니다. 본문·응답 제한은 1 MiB입니다. 8개 활성 듀얼과 64개 활성 요청, 최근 256개 종료 기록을 보유합니다.

| 경로 | 역할 |
|---|---|
| POST `/v1/requests` | DLL 클라이언트가 요청 발행 |
| GET `/v1/pending` | 앱이 판단할 요청 목록 조회 |
| GET `/v1/requests/{decisionId}` | 승인·소비·종료 상태 조회 |
| POST `/v1/decisions` | 앱이 선택한 후보 ID 제출 |
| POST `/v1/acks` | 클라이언트 소비 확인 또는 앱의 실패 반환 |
| POST `/v1/duels/end` | 듀얼 세대 종료 |

요청 필드: `protocolVersion=1`, `duelId`, `duelGeneration`, `decisionId`, `requestSequence`, `actor`, `requestKind`, `rawRequest`, `observation`, `choices`, `constraints`, UTC `deadline`. 새 요청에는 단조 증가하는 sequence가 필요합니다. 새 세대는 이전의 미완료 요청을 취소합니다. 종료된 세대의 지연 결과는 거절합니다.

후보는 `actionId`, `semanticKind`, `text`, `cardReferences`, `arguments`를 갖습니다. 후보를 실제 setter에 매핑하는 함수는 클라이언트에만 남습니다. 앱·Jev는 메모리 주소나 임의 setter를 반환할 수 없습니다.

제약은 `min`, `max`, `ordered`, `allowEmpty`, `legality`입니다. `single`은 정확히 한 후보, `independent`는 확인된 독립 선택, `allowed_selections`는 명시한 `allowedSelections`만 허용합니다. `unknown`에서는 결과를 받지 않습니다. 생산 DLL decoder는 아직 다중 선택의 독립성을 입증하지 않아 이를 `unknown`으로 발행합니다.

응답 필드: 동일한 `protocolVersion/duelId/duelGeneration/decisionId/actor`, `actionIds`, `provider`, `model`, 선택적 `confidence`. 모델이 보낸 ID·수량·중복·순서를 서버와 엔진 스레드에서 다시 검사합니다. 같은 ID·같은 내용 재전송은 멱등적이며 다른 내용 재사용은 409입니다.

상태는 `pending → accepted → applied`입니다. 취소·거절·기한 초과는 `cancelled/rejected/expired`입니다. `accepted`는 서버가 응답을 검사했다는 뜻입니다. `applied`는 클라이언트가 setter를 실행하고 엔진 요청이 소비됐음을 확인한 뒤에만 반환합니다. 앱의 `rejected`는 소비 확인이 아닙니다.

엔진 호출은 SysAct 스레드에서만 일어납니다. 통신 worker는 복사한 JSON을 보내고 결과를 큐에 넣습니다. queued 결과는 현재 session·actor·marker·deadline을 검사한 뒤 한 번만 적용합니다. 목록 콜백은 56이지만 busy 조회는 55이므로 두 번호를 같은 대기 session에 연결합니다. 단일 목록은 index와 결과 수 1, 다중 목록은 미선택 0·선택 순위 1..n과 결과 수를 사용합니다. 다중 결과 계약은 합성 검사에서만 검증됐습니다.

Jev 요청은 [공식 API](https://docs.typesafe.ai/api)의 `state`와 `questions.action` Choice를 사용하며 초기 모델은 `jev-1.13.0`입니다. criteria는 후보 ID→자연어 문구입니다. 255개 옵션 제한을 지키고, 별도 tokenizer 없이 보수적인 30,000 UTF-8 byte 제한을 둡니다. 이 제한은 Jev의 공식 token 제한과 동일하다는 주장이 아닙니다. 429·529·연결 실패만 기한 내 최대 3회 재시도합니다. 결정은 제출 전에 캐시해 HTTP 응답 손실로 Jev를 다시 호출하지 않습니다.
