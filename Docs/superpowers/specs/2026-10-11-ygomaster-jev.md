YgoMaster 포크 + Jev 결정 앱 개발 설계 검토안
2026-10-11 / 사용자 승인 설계. 현재 구현·검증 상태는 Docs/external-ai/README.md와 coverage.md 참조.

사용자 목표
1. YgoMaster의 DLL 훅을 이용해 Jev 호출 앱과 통신한다.
2. Jev 앱은 상태머신으로 듀얼 맥락을 유지하며 Jev를 호출한다.
3. Jev 결과가 YgoMaster 서버를 거쳐 CPU 행동을 제어한다.
4. 주된 개발 대상은 외부 앱 통신 인터페이스와 맥락 있는 자연어 선택지다.

완료 기준
소스 fork와 실제 빌드, DLL 요청→서버→별도 앱→Jev→서버→엔진 입력의 연결,
듀얼/요청 맥락과 중복·지연·종료 처리, 자연어 선택지와 원래 입력의 정확한 매핑,
원래 CPU 평가 우회, 대표 실제 효과/체인/다중 선택에서의 입력 왕복 증거가 필요하다.
합성 테스트나 Jev 요청 JSON 생성만으로 전체 목표를 완료로 표시하지 않는다.
승률 향상은 이번 사용자 목표에 없으므로 완료 조건으로 추가하지 않는다.

확인한 현재 상태
- upstream master는 연구 기준과 같은 0e2078237d46c2450f3a18697b8a756df256b8e9.
- GitHub 계정 tearight 로그인 확인; tearight/YgoMaster는 아직 존재하지 않음.
- D:\YGOMaster Tools는 local-only이고 현재 clean. YgoMaster 소스를 기존 제품 의존성으로
  추가하지 않는 지침이 있으나 사용자는 이번에 YgoMaster fork 개발을 명시적으로 요청함.
  모딩툴·Catalog·캠페인 소스와 분리해 Tools가 관리하는 별도 fork checkout으로 개발한다.
- Solo 듀얼 CPU의 실제 실행 주체는 게임 클라이언트의 duel.dll.
  서버에만 API를 추가하면 CPU가 바뀌지 않는다.
- 기존 DuelDll은 SetEffectDelegate, SysAct, 입력 export 훅과
  ActionsToRunInNextSysAct를 갖고 있어 새 주입 프레임워크가 필요하지 않음.
- .NET SDK는 없으나 upstream Build.bat가 사용하는 Windows .NET Framework
  MSBuild/csc는 존재함. C# 빌드는 기존 방식부터 확인하고 필요할 때만 도구를 추가한다.

설계와 대안
추천: DLL 훅 ↔ YgoMaster 서버 결정 중계 ↔ 별도 Jev 앱.
서버를 거쳐 결과를 반환한다는 사용자의 요구에 직접 대응한다.
DLL 훅↔Jev 앱 직접 연결은 단순하지만 서버 제어 경로 요구를 만족하지 않는다.
전체 듀얼을 서버 DLL로 이전하는 방식은 Solo 실행 모델을 크게 바꾸므로 이번에 선택하지 않는다.

구성 요소
A. YgoMasterClient의 외부 AI 입력 경계
   외부 AI 대상 Solo 플레이어를 외부 입력 타입으로 설정해 원래 CPU 판단을 우회한다.
   모든 인간 플레이어를 변환하지 않고 기존 Solo/Replay/PvP를 구별한다.
   WaitInput/RunDialog/RunList 이벤트에서 actor·snapshot·choices를 확보한다.
   getter와 setter는 엔진 스레드에서 호출한다. 네트워크는 별도 worker에서 처리한다.
   기존 표시/애니메이션 콜백을 보존하고 외부 AI 소유 입력만 보류한다.
   player type 전환만으로 우회되지 않는 실제 경로가 드러나면 해당 내부 경계를 버전
   검증 뒤 좁게 교체한다. C2A4F0 반환0을 대기로 쓰지 않는다.

B. YgoMasterServer의 결정 중계
   별도 loopback 통신 경로에서 요청·결과·적용 확인을 중계한다.
   API 경로를 게임 계정 인증/저장 API와 분리한다. 전송에는 별도 로컬 bridge token을 사용한다.
   엔진 snapshot과 candidate map을 기준으로 응답을 검사하고 승인된 결과만 클라이언트에 전달한다.
   같은 decisionId 재전송은 같은 요청/결과로 취급하고 다른 payload 재사용은 거절한다.
   명시적 applied 확인 전에 결정이 적용됐다고 표시하지 않는다.
   서버에는 DLL 입력을 직접 적용할 수 있다는 가정을 넣지 않는다.

C. 별도 Jev 호출 앱
   우선 Python 표준 라이브러리의 HTTP/JSON과 상태 관리로 구현한다.
   API key는 앱만 보관한다. 게임 클라이언트·서버·로그에는 전송하지 않는다.
   듀얼별 상태: 기다림 → 요청 수신 → 맥락/선택지 구성 → Jev 대기 → 응답 검증
   → 서버 반환 → 엔진 적용 확인 → 다음 요청. 종료/취소/실패는 명시적인 별도 상태다.
   retry는 현재 decisionId의 상태/기한을 다시 확인한 뒤 수행한다.
   재연결 때 서버가 여전히 소유한 요청만 재개한다. 메모리에 없는 맥락을 생성하지 않는다.
   테스트용 결정 provider와 실제 Jev provider를 선택할 수 있게 하되 테스트 모드 성공을
   Jev 호출 성공으로 기록하지 않는다.

통신 계약 초안
요청: protocolVersion, duelId, duelGeneration, decisionId, requestSequence,
actor, requestKind, rawRequest, observation, choices, constraints, deadline.
choice: actionId, text, cardReferences, semanticKind. 엔진 setter payload는
클라이언트가 보유한 후보 map에 남기고 모델에는 쓰기 명령/임의 메모리 주소를 노출하지 않는다.
결과: 동일한 duelGeneration/decisionId, 선택 actionId 또는 순서 있는 actionIds,
provider/model, 판단 confidence, 처리 상태.
적용 확인: accepted/applied/rejected/cancelled/expired와 사유.
stale·다른 actor·없는 후보·중복 선택·불연속 순위·허용되지 않은 빈 선택은 거절한다.
길이 제한·요청 수 제한·시간 제한은 실제 통신 경계에서 검사한다.

맥락과 자연어 choices
- LLM을 써서 선택지 문장을 생성하지 않는다.
- 카드ID→이름/설명은 upstream YdkHelper.LoadCardDataFromGame과 동일한 데이터 계약을 활용한다.
- SelectItemStr/ItemMsg/MixData의 문자열 ID는 DLG_Text/WORD_Text 등 실제 게임 데이터에 연결한다.
  ID 대응이 아직 미해석인 요청에서 임의 문구를 정확한 효과 설명으로 표기하지 않는다.
- 명령 유형, 카드 인스턴스의 관측 가능한 위치, 수량·순서 조건을 문장 틀로 표현한다.
- 같은 카드의 서로 다른 효과는 현재 옵션 문구/효과 참조로 구분한다. 카드 설명 전체를
  해당 옵션의 정확한 효과 설명인 것처럼 붙이지 않는다.
- 맥락은 현재 보드 + 공개 이벤트 이력 + 진행 중인 효과/코스트/대상 선택 관계를 유지한다.
  전 요청과 관계가 확인되지 않으면 unknown으로 남긴다.
- 상대 패·덱 순서·뒷면 카드 정체성은 관측에서 제외한다.
- 다중 카드 선택은 전체 합법 조합이 알려진 경우에만 조합 label을 만든다.
  단계 선택을 지원할 때는 각 단계의 후보·완료 제약을 확인한다. 후보 membership와
  min/max만으로 조합 전체가 합법이라고 가정하지 않는다.
- 숫자·종족·속성·위치·정렬·특수 선언을 각각 decoder와 응답 계약으로 다룬다.
  해석되지 않은 유형은 명시적 unsupported 상태로 처리하고 임의 입력을 제출하지 않는다.

Jev 공식 호출
POST https://api.typesafe.ai/v1/systemone
model=jev-1.13.0으로 초기 비교를 고정. state는 우리 관측/맥락 JSON,
questions의 Choice criteria는 actionId→자연어 설명.
응답 answers.<질문>.choice를 서버 후보 map과 대조한다.
Jev Choice는 단일 선택이고 최대255개 옵션이다. 여러 질문의 병렬 응답을 순차 선택으로
오인하지 않는다. 숫자 합계·소재 제약·수량·응답 유효성은 코드가 검사한다.
429/529 retry와 연결 실패는 요청 기한 및 종료 상태를 고려한다.
https://docs.typesafe.ai/api
https://docs.typesafe.ai/models

개발 순서
1. GitHub fork와 별도 local checkout/작업 branch를 만들고 기존 C# 빌드를 확인.
2. 같은 버전 계약을 쓰는 서버 bridge와 외부 앱 상태머신을 구현.
3. 자연어 renderer를 게임 카드 데이터/문자열 parser에 연결하고 대표 fixture로 검증.
4. 기존 DLL callback·SysAct 큐에 요청 보류/응답 적용을 연결.
5. 모의 provider로 실제 구성 요소 왕복·지연·중복·종료 검증.
6. 독립 DLL 호스트에서 정상 초기화와 입력 유형별 실제 요청/응답 검증.
7. 실제 Jev 인증이 제공된 환경에서 호출 및 입력 왕복 검증.
8. Solo 실행 환경 통합은 준비한 변경/실험을 검토 가능한 상태로 만든 후 수행.
   설치·저장 파일을 임의로 덮어쓰지 않는다.

검증 기준
- 실제 C# client/server 컴파일.
- 별도 프로세스 app/server 통신과 요청→응답→applied 흐름.
- stale·중복·timeout·취소·새 듀얼·후속 선택 맥락의 대표 검사.
- 카드명/선택지 문장과 엔진 후보의 일치.
- CPU 평가가 미실행인 경로에서 실제 엔진 입력이 소비되는 증거.
- 체인·소재·특수 선언 등 미지원 항목은 완료된 척하지 않고 계속 추적.
- 실제 Jev 호출, 실제 DLL 합성 검사, 정상 초기화 듀얼, 게임 클라이언트 관찰은
  서로 다른 검증 범위로 보고한다.

격리와 소유
fork 개발은 Tools 소유의 별도 checkout에서 수행하고 Solo 캠페인을 변경하지 않는다.
Tools 자체 저장소는 원격 push/외부 공개하지 않는다.
DLL 파일 수정은 없으며 내부 RVA를 사용하는 코드는 SHA/revision gate를 포함한다.
API key·게임 인증정보·저장 데이터·대량 자산은 Git에 포함하지 않는다.
새 주입기·DB·웹 관리 화면·클라우드 배포는 현재 목표에 필요하지 않으므로 추가하지 않는다.

현재 승인 단계
사용자가 설계를 승인했다. tearight/YgoMaster fork와 jev-external-ai branch에서 구현 중이다.
정상 초기화 DLL과 모의 앱의 왕복은 검증했으며 실제 Jev·게임 화면 통합 검증은 남아 있다.
