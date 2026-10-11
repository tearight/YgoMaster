# 2026-10-12 검증 범위

## 확인한 결과

| 검사 | 결과 | 범위 |
|---|---|---|
| client/server Framework C# 빌드 | 성공 | 기존 MSBuild/csc 사용. .NET 4.8 참조 팩 부재로 설치된 GAC를 사용하는 경고가 남음 |
| bridge/app/수동 더미 자동 검사 | 19개 통과 | 기존 18개 + 터미널 번호/Boolean 입력·잘못된 답 재입력·취소·늦은 취소, 실제 HTTP 1/0 반환 |
| 실제 터미널 연습 입력 | 통과 | 실행 도우미의 -Practice로 시작해 2와 false 입력. choice=end, 가중치 summon=0/end=1, noul=0 반환 후 종료 코드 0 |
| InputSession 검사 | 통과 | 엔진 스레드 소유, 한 번 적용, 순서 매핑, 지연 session 거절, 명시적 소비 확인 |
| 실제 추출 카드 데이터 | 14,323개 읽음 | 카드 ID→이름·설명. 원본 자산은 읽기만 함 |
| 정상 초기화 DLL — basic | 8개 consumed / 8개 applied | 효과 확인, 일반 소환, 위치 선택, 필드 반영, 페이즈 이동 |
| 정상 초기화 DLL — spell-target | 16개 consumed / 16개 applied | MST 세트→배치→발동→대상 선택. 선택 UID가 후속 묘지에 존재함을 대조 |
| 정상 초기화 DLL — discard-two | 8개 consumed / 8개 applied | Graceful Charity의 2장 버리기. 남은 장수 2→1, 기본값과 다른 패 인덱스 선택, 선택 UID 75·63의 실제 묘지 이동을 대조 |
| 정상 초기화 DLL — twin-target | 20개 consumed / 20개 applied | Twin Twisters의 코스트 1장→첫 대상→추가 대상 질문→둘째 대상. 코스트 UID 43과 대상 UID 65·15가 실제 묘지에 존재함을 대조 |
| 입력 창 대기 재현 | 수정 전 0개 consumed, 서버 accepted에서 정지 / 수정 후 basic 16개 applied | 제출 후 원래 화면이 입력 버튼을 기다리는 상황을 모의. 외부 소유 요청의 busy를 제출 후 0으로 반환하도록 수정 |
| 실제 native Hook<T> — basic | 16개 consumed / 16개 applied | 기존 loader의 MinHook으로 export 6개와 CPU 계측 5개 연결. 상충하는 입력 16개 차단, 원래 view 콜백 103개 전달 |
| 실제 native Hook<T> — twin-target | 20개 consumed / 20개 applied | 동일한 훅·화면 대기 조건에서 코스트/두 대상의 묘지 이동 대조도 통과 |
| 실제 native Hook<T> — chain-cost | 20개 consumed / 20개 applied | 상대 Graceful Charity→Magic Jammer→패 한 장 코스트. 체인 출처·순서·역순 해결, 마법 무효화/파괴, 세 카드의 묘지 이동을 대조 |
| 실제 native Hook<T> — deck-order | 24개 consumed / 24개 applied | Spellbook Organization의 순서 6개 생성. 목록 3→2→1로 덱 위 3장을 정렬하고 첫 UID가 다음 턴 드로우로 패에 들어온 것을 대조 |
| 실제 native Hook<T> — 앱 재시작 | 8개 consumed / 8개 applied | 세 번 적용한 뒤 별도 모의 앱 프로세스를 종료·재실행. 첫 후속 판단에 앞선 적용 ID 3개가 모두 포함됨을 대조 |
| 실제 native Hook<T> — human 브라우저 선택 | 6개 consumed / 6개 applied | 브라우저에서 효과 확인·패 2번째 카드 소환·필드 구역 3 배치를 선택. UID 15가 실제 필드 position 2에 존재함을 대조. provider는 human, 확인값은 모두 정수 1 |
| 브라우저 연습 질문 | 통과 | Choice와 Noul을 함께 표시하고, 모든 질문에 답하기 전 제출 불가. Choice의 선택/비선택은 1/0, Noul의 false는 0으로 실제 HTTP 반환. 2500×1400 화면 확인 |
| 일반 JSON 맥락 표시 | 통과 | 게임 전용 구조와 다른 state도 원문으로 표시하고 Noul 질문을 유지. 브라우저의 true 선택을 정수 1로 실제 HTTP 반환 |
| 게임 안내 문자열 | DLG 785개·WORD 257개 읽음 | 현재 추출 자산의 ID별 offset·범위·UTF-8 검사. 실제 요청에서 DLG 33 질문과 581 안내/카드명 치환을 검증. 모든 ID의 듀얼 사용이나 치환 타입을 검증한 것은 아님 |
| 실제 Jev endpoint 인증 | 이번 단계 대상 아님 | 사용자 요청에 따라 로컬 human 더미로 인터페이스를 검증하며 실제 API를 호출하지 않음 |
| 게임 화면·주입 훅·UI 대기 경합 | 미검증 | 독립 DLL host는 이 범위를 재현하지 않음 |
| 다중 소재·합계·다른 정렬·선언 | 미완료 | 순차 버리기/대상 선택/확인된 3장 정렬은 다른 소재 조합의 합법성 증명이 아님 |

DLL host는 생산 decoder/controller/worker를 그대로 컴파일하고, IL2CPP·UI 바인딩만 export shim으로 대체합니다. 실제 게임에서 추출한 카드 데이터를 넣고 `DuelSysInitCustom`으로 초기화합니다. 재현을 위한 test deck은 같은 카드를 40장 넣은 fixture이며, 일반 덱 구성의 적법성을 검증하는 검사는 아닙니다. 실행 중인 게임에 주입하지 않고, DLL 파일·게임 설치·Solo 저장 파일을 수정하지 않습니다.

제어 대상 player type이 Human(0)인 상태에서 엔진이 외부 입력을 소비했습니다. 기존 연구에서 이 타입이 CPU 평가 분기를 우회함을 확인했습니다. 추가 native-hook basic fixture는 원래 함수로 전달하는 계측 훅을 넣었습니다. 제어 대상 player 1은 main/battle/timing/other/dialog 진입이 모두 0이었으며, player 0은 main 97회·other 3회·dialog 20회로 계측이 활성화됨을 확인했습니다. 이 증거의 범위는 해당 정상 초기화 듀얼의 관측한 경로입니다. 모든 카드와 실제 게임 화면의 전체 실행을 계측한 것으로 확대하지 않습니다.

모의 provider 성공과 실제 Jev 성공은 구분합니다. 앞선 자동 듀얼 fixture는 `mock`을, 이전 브라우저 검사는 `human`을 사용했습니다. 선택지 문구는 두 경우 모두 LLM 없이 생성합니다. 현재 터미널 변경은 사람의 입력 방식만 바꾸며, DLL과 연결 앱의 계약은 유지합니다. 앞선 DLL 검사를 반복하지 않고 변경한 터미널 입력과 HTTP 반환을 확인했습니다.

버리기·Twin Twisters·Magic Jammer·덱 정렬 fixture는 검사용 별도 provider를 사용합니다. 버리기에서는 마지막 합법 후보를 고르고, Twin Twisters에서는 두 카드를 세트한 뒤 추가 대상 질문에 동의하며, Magic Jammer에서는 상대 마법에 대응하고, 덱 정렬에서는 마지막 순서 후보를 고릅니다. 생산 앱의 Jev 선택을 대신하는 규칙이 아닙니다. Runner는 선택한 카드의 묘지 UID 또는 실제 덱 순서·다음 드로우를 자동 대조하며, 소비/적용 횟수가 맞더라도 이 대조가 실패하면 실패로 종료합니다. 각 기록의 source hash를 보존하므로 앞선 basic/spell-target 검사와 추가 검사의 소스 버전을 구분할 수 있습니다.

native-hook 검사는 기존 `YgoMasterLoader.dll`을 소유한 host에 읽어 넣고 생산 `Hook<T>`를 사용합니다. SetWork·SetEffectDelegate·SetPlayerType·DlgSetResult·ComDoCommand·SysAct의 실제 export 호출을 가로채며, controller/worker/decoder는 생산 코드를 그대로 컴파일합니다. view와 SysAct 연결 어댑터는 host 전용입니다. IL2CPP 생성자나 게임 화면을 실행하는 검사는 아닙니다. `--ui-waits-for-input`은 제출 후에도 view가 버튼 입력을 기다린다는 상황을 재현합니다. 외부 요청과 맞는 busy 호출은 기다리는 동안 1, 제출 후 0으로 처리하고 다른 표시/애니메이션 콜백은 계속 전달합니다.

## 추가로 확인한 입력 계약

검증한 DLL의 `5d7990` 함수는 Discard(16)·Update(18)·Close(19)를 안내/갱신 이벤트로 보냅니다. 실제 버리기는 `WaitInput`의 Selection(8), 종류 32~34에서 한 장씩 받습니다. `work+3dbc`의 남은 장수와 패의 현재 `Decide` 명령 비트를 읽고, 선택한 패 인덱스에 `DuelComDoCommand(..., Decide)`를 보냅니다. 다중 목록 setter나 dialog bitmask로 대신하지 않습니다. 적용 직전에는 카드 UID와 명령 비트를 다시 확인합니다.

YesNo의 `p2`는 실제 질문의 DLG ID입니다. 혼합 문자열은 앞선 설명입니다. 실제 Twin Twisters 요청에서 `p2=33`은 “다른 마법·함정을 파괴할까?”이며, 혼합 버퍼의 DLG 581 + InsCard 12175는 “Twin Twisters가 발동됐다”입니다. AddString·AddCr·InsCard를 처리하며, 이름 치환은 현재 공개/자신 카드로 확인된 ID에 한합니다. 다른 혼합 타입이나 남은 `%s/%d`는 해석된 문장으로 표시하지 않습니다.

체인 출처는 해당 DLL의 `10dd0c` 생산자가 패킷 상위 16비트에 담은 UID와 위치를 실제 공개 카드에 대조합니다. 하위 native 토큰과 p1의 소유/제어 정보는 체인 순서로 해석하지 않습니다. 전부 해결되면 현재 체인을 비우고, 다음 체인의 받은 순서는 1부터 시작합니다. Python 앱은 체인·공개 이벤트의 카드 참조도 비공개 정보를 제거한 뒤 이름·설명을 보완합니다. 서로 독립된 참조를 사용한 통합 검사로 이 처리와 정보 차단을 확인했습니다.

chain-cost에서 상대 마법 UID 12와 Magic Jammer UID 65의 체인을 관측했습니다. 코스트는 기본값과 다른 패 인덱스 3의 UID 43을 선택했습니다. Magic Jammer→Graceful Charity 순으로 해결됐고, 상대 마법의 CardDisable·CardBreak를 확인했습니다. 첫 체인 범위에는 드로우 이벤트가 없으며 이후 무효화되지 않은 Graceful Charity에는 드로우 이벤트가 있어 검출이 실제로 작동함을 대조했습니다. UID 12·65·43은 모두 실제 묘지에 존재했습니다. 상충 입력 20개 차단, view 콜백 219개 전달, 제어 대상 CPU 평가 진입 0회도 확인했습니다. 이 한 카운터 함정의 증거를 모든 체인·효과 유형의 완료로 확대하지 않습니다.

동일한 20개 요청을 생산 Python 앱으로 오프라인 재구성해 체인 출처의 이름·설명이 provider 상태에 포함되는지 확인했습니다. 적용 이력까지 넣은 Jev 형식 본문의 최대 크기는 13,632 UTF-8 byte로 현재 앱의 30,000 byte 제한 이내였습니다. 네트워크로 Jev에 전송한 검사가 아닙니다.

deck-order의 수정 전에는 실제 목록 요청 `[56, 1, 9, 0]`, 3장/3장 제약을 `unknown`으로 처리해 6개 입력만 적용하고 CPU로 복귀했습니다. 수정 후에는 해결 중인 Spellbook Organization(5676)의 공개 출처, 자기 덱에서 온 서로 다른 UID 3개, 목록 타입·정확한 장수를 모두 확인한 경우에만 전체 순서가 독립임을 인정합니다. 목록 UID 67·63·75를 기본값과 다른 75→63→67로 정렬했습니다. 후속 엔진 덱 순서가 일치하고 나머지 카드 순서는 유지됐으며, 다음 자기 턴의 실제 드로우 후 UID 75가 패에 존재했습니다. 활성화 요청과 출처 UID도 일치해 parentDecisionId가 연결됐습니다. 비공개 전체 덱 순서는 검사용 host 기록에만 있으며 서버·앱 관측에는 포함되지 않습니다.

이 검증의 main/battle/timing/other/dialog 계측 5종은 제어 대상 진입 0회였습니다. 상대 CPU는 main 190·timing 43·other 3·dialog 182회로 계측이 살아 있음을 확인했습니다. native 목록 생성자의 사전 순위는 제출 전에 전부 지우고 외부 순위 1..3으로 교체합니다. 목록 사전 계산까지 전부 차단한 것으로 해석하지 않습니다. 표시 콜백 167개 전달과 상충 입력 24개 차단도 확인했습니다.

## 재현

큰 대기 요청 두 건의 합계 응답이 1 MiB를 넘으면 앱이 `response_too_large`로 중단되는 오류를 재현했습니다. 수정 후에는 각각 약 600 KB인 유효 요청 두 건을 제한 안의 묶음으로 받아 순서대로 처리하고 다음 조회가 빈 목록임을 확인했습니다. 전체 기록 크기를 넘기는 결정 제출은 413으로 거절하고 기존 pending 상태를 유지했습니다. 본문은 제한 안이지만 응답 포장을 포함하면 너무 큰 새 요청도 413으로 거절하며 서버에 기록이 생기지 않음을 대조했습니다. 변경된 서버의 계약 검사는 15개 통과했습니다. 앞선 native 입력 검사의 소스·서버 버전은 각 기록의 hash로 보존하며, 이 변경을 이유로 같은 native 검사를 반복하지 않았습니다.

앱 재시작 검증에서는 서버와 native host를 유지하고 모의 앱만 종료·재실행했습니다. 새 앱의 첫 판단에 앞선 적용 ID 3개가 동일한 순서로 복구됐습니다. 총 8건 적용, 상충 입력 8개 차단, 표시 콜백 48개 전달을 확인했습니다. 별도 계약 검사에서는 이전 세대·다른 actor·미적용·후속 sequence를 제외하고, 큰 이력이 1 MiB를 넘지 않도록 최근 일부만 반환하는 것을 대조했습니다. 순서 선택의 적용 이력은 후보 목록 순서가 아니라 제출한 actionIds 순서로 기록합니다. 처리 중인 요청의 duel_end/new_generation 취소를 받으면 그 맥락을 비웁니다. 서버 재시작이나 모든 과거 이력의 영속 저장을 검증한 것은 아닙니다.

fork 루트에서 먼저 빌드하고 계약 검사를 실행합니다.

```powershell
& "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\MSBuild.exe" YgoMaster.sln /p:Configuration=Debug /p:Platform=x64 /nologo /v:quiet
& .\tools\external-ai\build-tests.ps1
```

정상 초기화 검사는 읽을 DLL·CardData의 절대 경로를 명시합니다. 검증된 hash가 아니면 실행하지 않습니다.

```powershell
py -3 tools\external-ai\run-dll-scenarios.py --dll '<duel.dll 절대 경로>' --data '<CardData 절대 경로>' --output '.local\native-basic' --scenario basic --decisions 8
py -3 tools\external-ai\run-dll-scenarios.py --dll '<duel.dll 절대 경로>' --data '<CardData 절대 경로>' --output '.local\native-spell-target' --scenario spell-target --decisions 16
py -3 tools\external-ai\run-dll-scenarios.py --dll '<duel.dll 절대 경로>' --data '<CardData 절대 경로>' --output '.local\native-discard-two' --scenario discard-two --decisions 8
py -3 tools\external-ai\run-dll-scenarios.py --dll '<duel.dll 절대 경로>' --data '<CardData 절대 경로>' --output '.local\native-twin-target' --scenario twin-target --decisions 20
py -3 tools\external-ai\run-dll-scenarios.py --dll '<duel.dll 절대 경로>' --data '<CardData 절대 경로>' --loader '<기존 YgoMasterLoader.dll 절대 경로>' --output '.local\native-hook-ui-basic' --scenario basic --decisions 16 --ui-waits-for-input
py -3 tools\external-ai\run-dll-scenarios.py --dll '<duel.dll 절대 경로>' --data '<CardData 절대 경로>' --loader '<기존 YgoMasterLoader.dll 절대 경로>' --output '.local\native-hook-ui-chain' --scenario chain-cost --decisions 20 --ui-waits-for-input
py -3 tools\external-ai\run-dll-scenarios.py --dll '<duel.dll 절대 경로>' --data '<CardData 절대 경로>' --loader '<기존 YgoMasterLoader.dll 절대 경로>' --output '.local\native-hook-ui-deck-order' --scenario deck-order --decisions 24 --ui-waits-for-input
py -3 tools\external-ai\run-dll-scenarios.py --dll '<duel.dll 절대 경로>' --data '<CardData 절대 경로>' --loader '<기존 YgoMasterLoader.dll 절대 경로>' --output '.local\native-hook-app-restart' --scenario basic --decisions 8 --ui-waits-for-input --restart-app-after 3
py -3 tools\external-ai\run-dll-scenarios.py --dll '<duel.dll 절대 경로>' --data '<CardData 절대 경로>' --loader '<기존 YgoMasterLoader.dll 절대 경로>' --output '.local\native-human-terminal' --scenario basic --provider human --decisions 6 --ui-waits-for-input --timeout 600
```

각 output의 `result.json`은 provider, source hash, 엔진 소비 ID, 서버 기록을 포함하고 `native.log/app.log/server.log`를 따로 남깁니다. 로컬 설정과 bridge token은 Git에서 제외됩니다.

human 검사에서는 더미 프로그램을 먼저 실행하고 터미널에서 각 질문을 직접 반환합니다. 전체 host 기한은 600초, 요청별 기한은 120초입니다. 앞선 브라우저 검사에서 최초 180초 host는 4건 적용 뒤 전체 기한이 끝났고, 늘린 기한의 최종 검사에서 6건 모두 적용됐습니다. 이 기록에는 표시 콜백 44개 전달과 상충 입력 6개 차단도 있습니다. 현재 터미널의 기한 초과 입력은 Enter를 누르면 폐기합니다. 실측 API 호출 없이 입력 인터페이스를 확인하는 검사입니다.

실제 키가 준비된 경우 같은 검사에 `--provider jev --decisions 3 --timeout 120`을 붙여 최소 호출로 연결을 확인할 수 있습니다. 이 검사는 실제 API 호출 비용이 발생합니다. 아직 수행하지 않은 검사의 예시 명령입니다.

현재 요청 범위인 수동 Jev 더미와 인터페이스의 왕복을 검증했습니다. 실제 Jev 왕복과 게임 화면의 전체 통합, 미지원 decoder 확장은 이후 별도 범위입니다.
