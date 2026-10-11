# 2026-10-11 검증 범위

## 확인한 결과

| 검사 | 결과 | 범위 |
|---|---|---|
| client/server Framework C# 빌드 | 성공 | 기존 MSBuild/csc 사용. .NET 4.8 참조 팩 부재로 설치된 GAC를 사용하는 경고가 남음 |
| bridge/app 자동 검사 | 10개 통과 | 실제 C# 서버와 Python 앱 프로세스, 인증·세대·기한·멱등성·합법 조합·실패 반환·비공개 정보·재시도 |
| InputSession 검사 | 통과 | 엔진 스레드 소유, 한 번 적용, 순서 매핑, 지연 session 거절, 명시적 소비 확인 |
| 실제 추출 카드 데이터 | 14,323개 읽음 | 카드 ID→이름·설명. 원본 자산은 읽기만 함 |
| 정상 초기화 DLL — basic | 8개 consumed / 8개 applied | 효과 확인, 일반 소환, 위치 선택, 필드 반영, 페이즈 이동 |
| 정상 초기화 DLL — spell-target | 16개 consumed / 16개 applied | MST 세트→배치→발동→대상 선택. 선택 UID가 후속 묘지에 존재함을 대조 |
| 실제 Jev endpoint 인증 | 미검증 | API 키 준비가 필요함 |
| 게임 화면·주입 훅·UI 대기 경합 | 미검증 | 독립 DLL host는 이 범위를 재현하지 않음 |
| 다중 소재·코스트·합계·정렬·선언 | 미완료 | 합성 입력과 계약 검사만 존재. 전체 목표 완료 근거가 아님 |

DLL host는 생산 decoder/controller/worker를 그대로 컴파일하고, IL2CPP·UI 바인딩만 export shim으로 대체합니다. 실제 게임에서 추출한 카드 데이터를 넣고 `DuelSysInitCustom`으로 초기화합니다. 재현을 위한 test deck은 같은 카드를 40장 넣은 fixture이며, 일반 덱 구성의 적법성을 검증하는 검사는 아닙니다. 실행 중인 게임에 주입하지 않고, DLL 파일·게임 설치·Solo 저장 파일을 수정하지 않습니다.

제어 대상 player type이 Human(0)인 상태에서 엔진이 외부 입력을 소비했습니다. 기존 연구에서 이 타입이 CPU 평가 분기를 우회함을 확인했습니다. 이번 host에는 CPU 내부 함수 진입 횟수 계측을 넣지 않았으므로, 이를 실제 게임 훅 전체의 CPU 미진입 계측으로 주장하지 않습니다.

모의 provider 성공과 실제 Jev 성공은 구분합니다. HTTP 형식 검사는 가짜 endpoint를 사용했습니다. 정상 듀얼 host의 provider는 `mock`이며 선택지 문구를 LLM으로 생성하지 않습니다.

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
```

각 output의 `result.json`은 provider, source hash, 엔진 소비 ID, 서버 기록을 포함하고 `native.log/app.log/server.log`를 따로 남깁니다. 로컬 설정과 bridge token은 Git에서 제외됩니다.

실제 키가 준비된 경우 같은 검사에 `--provider jev --decisions 3 --timeout 120`을 붙여 최소 호출로 연결을 확인할 수 있습니다. 이 검사는 실제 API 호출 비용이 발생합니다. 아직 수행하지 않은 검사의 예시 명령입니다.

전체 목표는 진행 중입니다. 남은 작업은 실제 Jev 왕복, 게임 화면에서의 훅·UI 경합 확인, 문자열 치환과 대표 다중 코스트·소재 경로의 decoder/실제 입력 검증입니다.
