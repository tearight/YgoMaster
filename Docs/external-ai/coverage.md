# 2026-10-11 검증 범위

## 확인한 결과

| 검사 | 결과 | 범위 |
|---|---|---|
| client/server Framework C# 빌드 | 성공 | 기존 MSBuild/csc 사용. .NET 4.8 참조 팩 부재로 설치된 GAC를 사용하는 경고가 남음 |
| bridge/app 자동 검사 | 12개 통과 | 실제 C# 서버와 Python 앱 프로세스, 인증·세대·기한·멱등성·합법 조합·실패 반환·비공개 정보·재시도·혼합 안내/질문 구분·문자열 offset 경계 |
| InputSession 검사 | 통과 | 엔진 스레드 소유, 한 번 적용, 순서 매핑, 지연 session 거절, 명시적 소비 확인 |
| 실제 추출 카드 데이터 | 14,323개 읽음 | 카드 ID→이름·설명. 원본 자산은 읽기만 함 |
| 정상 초기화 DLL — basic | 8개 consumed / 8개 applied | 효과 확인, 일반 소환, 위치 선택, 필드 반영, 페이즈 이동 |
| 정상 초기화 DLL — spell-target | 16개 consumed / 16개 applied | MST 세트→배치→발동→대상 선택. 선택 UID가 후속 묘지에 존재함을 대조 |
| 정상 초기화 DLL — discard-two | 8개 consumed / 8개 applied | Graceful Charity의 2장 버리기. 남은 장수 2→1, 기본값과 다른 패 인덱스 선택, 선택 UID 75·63의 실제 묘지 이동을 대조 |
| 정상 초기화 DLL — twin-target | 20개 consumed / 20개 applied | Twin Twisters의 코스트 1장→첫 대상→추가 대상 질문→둘째 대상. 코스트 UID 43과 대상 UID 65·15가 실제 묘지에 존재함을 대조 |
| 입력 창 대기 재현 | 수정 전 0개 consumed, 서버 accepted에서 정지 / 수정 후 basic 16개 applied | 제출 후 원래 화면이 입력 버튼을 기다리는 상황을 모의. 외부 소유 요청의 busy를 제출 후 0으로 반환하도록 수정 |
| 실제 native Hook<T> — basic | 16개 consumed / 16개 applied | 기존 loader의 MinHook으로 export 6개와 CPU 계측 5개 연결. 상충하는 입력 16개 차단, 원래 view 콜백 103개 전달 |
| 실제 native Hook<T> — twin-target | 20개 consumed / 20개 applied | 동일한 훅·화면 대기 조건에서 코스트/두 대상의 묘지 이동 대조도 통과 |
| 게임 안내 문자열 | DLG 785개·WORD 257개 읽음 | 현재 추출 자산의 ID별 offset·범위·UTF-8 검사. 실제 요청에서 DLG 33 질문과 581 안내/카드명 치환을 검증. 모든 ID의 듀얼 사용이나 치환 타입을 검증한 것은 아님 |
| 실제 Jev endpoint 인증 | 미검증 | API 키 준비가 필요함 |
| 게임 화면·주입 훅·UI 대기 경합 | 미검증 | 독립 DLL host는 이 범위를 재현하지 않음 |
| 다중 소재·합계·정렬·선언 | 미완료 | 순차 버리기/대상 선택 검증은 다른 소재 조합의 합법성 증명이 아님 |

DLL host는 생산 decoder/controller/worker를 그대로 컴파일하고, IL2CPP·UI 바인딩만 export shim으로 대체합니다. 실제 게임에서 추출한 카드 데이터를 넣고 `DuelSysInitCustom`으로 초기화합니다. 재현을 위한 test deck은 같은 카드를 40장 넣은 fixture이며, 일반 덱 구성의 적법성을 검증하는 검사는 아닙니다. 실행 중인 게임에 주입하지 않고, DLL 파일·게임 설치·Solo 저장 파일을 수정하지 않습니다.

제어 대상 player type이 Human(0)인 상태에서 엔진이 외부 입력을 소비했습니다. 기존 연구에서 이 타입이 CPU 평가 분기를 우회함을 확인했습니다. 추가 native-hook basic fixture는 원래 함수로 전달하는 계측 훅을 넣었습니다. 제어 대상 player 1은 main/battle/timing/other/dialog 진입이 모두 0이었으며, player 0은 main 97회·other 3회·dialog 20회로 계측이 활성화됨을 확인했습니다. 이 증거의 범위는 해당 정상 초기화 듀얼의 관측한 경로입니다. 모든 카드와 실제 게임 화면의 전체 실행을 계측한 것으로 확대하지 않습니다.

모의 provider 성공과 실제 Jev 성공은 구분합니다. HTTP 형식 검사는 가짜 endpoint를 사용했습니다. 정상 듀얼 host의 provider는 `mock`이며 선택지 문구를 LLM으로 생성하지 않습니다.

새 두 fixture는 검사용 별도 provider를 사용합니다. 버리기에서는 마지막 합법 후보를 고르고, Twin Twisters에서는 두 카드를 세트한 뒤 추가 대상 질문에 동의합니다. 생산 앱의 Jev 선택을 대신하는 규칙이 아닙니다. Runner는 선택한 카드와 실제 묘지 UID를 자동 대조하며, 소비/적용 횟수가 맞더라도 이 대조가 실패하면 실패로 종료합니다. 각 기록의 source hash를 보존하므로 앞선 basic/spell-target 검사와 추가 검사의 소스 버전을 구분할 수 있습니다.

native-hook 검사는 기존 `YgoMasterLoader.dll`을 소유한 host에 읽어 넣고 생산 `Hook<T>`를 사용합니다. SetWork·SetEffectDelegate·SetPlayerType·DlgSetResult·ComDoCommand·SysAct의 실제 export 호출을 가로채며, controller/worker/decoder는 생산 코드를 그대로 컴파일합니다. view와 SysAct 연결 어댑터는 host 전용입니다. IL2CPP 생성자나 게임 화면을 실행하는 검사는 아닙니다. `--ui-waits-for-input`은 제출 후에도 view가 버튼 입력을 기다린다는 상황을 재현합니다. 외부 요청과 맞는 busy 호출은 기다리는 동안 1, 제출 후 0으로 처리하고 다른 표시/애니메이션 콜백은 계속 전달합니다.

## 추가로 확인한 입력 계약

검증한 DLL의 `5d7990` 함수는 Discard(16)·Update(18)·Close(19)를 안내/갱신 이벤트로 보냅니다. 실제 버리기는 `WaitInput`의 Selection(8), 종류 32~34에서 한 장씩 받습니다. `work+3dbc`의 남은 장수와 패의 현재 `Decide` 명령 비트를 읽고, 선택한 패 인덱스에 `DuelComDoCommand(..., Decide)`를 보냅니다. 다중 목록 setter나 dialog bitmask로 대신하지 않습니다. 적용 직전에는 카드 UID와 명령 비트를 다시 확인합니다.

YesNo의 `p2`는 실제 질문의 DLG ID입니다. 혼합 문자열은 앞선 설명입니다. 실제 Twin Twisters 요청에서 `p2=33`은 “다른 마법·함정을 파괴할까?”이며, 혼합 버퍼의 DLG 581 + InsCard 12175는 “Twin Twisters가 발동됐다”입니다. AddString·AddCr·InsCard를 처리하며, 이름 치환은 현재 공개/자신 카드로 확인된 ID에 한합니다. 다른 혼합 타입이나 남은 `%s/%d`는 해석된 문장으로 표시하지 않습니다.

## 재현

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
```

각 output의 `result.json`은 provider, source hash, 엔진 소비 ID, 서버 기록을 포함하고 `native.log/app.log/server.log`를 따로 남깁니다. 로컬 설정과 bridge token은 Git에서 제외됩니다.

실제 키가 준비된 경우 같은 검사에 `--provider jev --decisions 3 --timeout 120`을 붙여 최소 호출로 연결을 확인할 수 있습니다. 이 검사는 실제 API 호출 비용이 발생합니다. 아직 수행하지 않은 검사의 예시 명령입니다.

전체 목표는 진행 중입니다. 남은 작업은 실제 Jev 왕복, 게임 화면에서의 훅·UI 경합 확인, 다른 혼합 문자열 타입과 다중 소재·합계·정렬·선언 경로의 decoder/실제 입력 검증입니다.
