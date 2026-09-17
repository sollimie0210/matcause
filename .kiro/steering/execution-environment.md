# 실행 환경 및 명령 실행 규칙

## 워크스페이스 위치 (OneDrive 동기화 경로)

이 프로젝트는 OneDrive 동기화 경로 안에 있다:

```
C:\Users\leun1\OneDrive\바탕 화면\대외활동\AI AWS 공모전
```

이 때문에 주의할 점:

- OneDrive 동기화 프로세스가 파일을 잠글 수 있어, 폴더 안에 `.venv`를 만들거나
  대량 파일 쓰기(`pip install` 등)를 할 때 `WinError 32`(파일 사용 중) 같은 오류가
  간헐적으로 발생할 수 있다.
- 무거운 명령을 인터랙티브 셸에서 직접 실행하면, 명령이 끝난 뒤에도 셸이 응답하지
  않는(먹통) 현상이 반복 관찰됐다. 특히 긴 실행 + OneDrive 경로 조합에서 심하다.
- Python 가상환경은 절대경로를 하드코딩하므로(`.venv`는 이식 불가), 워크스페이스를
  옮기면 `.venv`는 그냥 복사하지 말고 새 위치에서 재생성해야 한다.

## 무거운 명령 실행 규칙 (기본값)

다음에 해당하는 "무거운" 명령은 **인터랙티브 셸에서 직접 돌리지 말고, 백그라운드
프로세스 + 로그 파일 방식**으로 실행한다:

- `pip install` / `uv pip install` (특히 pymatgen, scikit-learn, faiss 등 대용량)
- 전체 `pytest` 실행
- `robocopy` / 대량 파일 복사·삭제
- 그 밖에 수십 초 이상 걸리거나 대량 파일 I/O를 하는 명령

### 실행 패턴

1. `control_pwsh_process`(start)로 명령을 백그라운드에서 실행한다.
2. 명령 출력은 로그 파일로 리다이렉트하고(`> some.log 2>&1` 또는 `*> some.log`),
   끝에 완료 표식(sentinel)을 남긴 뒤 `Start-Sleep`로 프로세스를 잠시 유지한다.
   예: `... > run.log 2>&1; Write-Output "DONE_SENTINEL"; Start-Sleep -Seconds 600`
3. 짧은 `Start-Sleep` 후 로그 파일을 `read_file`로 읽어 결과·완료 여부를 확인한다.
   (인터랙티브 셸의 stdout은 echo 잡음이 심해 신뢰하지 않는다. 로그 파일이 진실.)
4. 확인이 끝나면 `control_pwsh_process`(stop)로 프로세스를 정리하고, 임시 로그
   파일도 삭제한다.

### 예외 (일반 실행 허용)

`Test-Path`, 짧은 상태 확인, 한두 파일 대상 명령 등 수 초 내에 끝나는 가벼운
명령은 일반 실행(`execute_pwsh`)으로 해도 된다.

## PowerShell 문법 유의

- 명령 구분자는 `;` 를 쓴다(`&&` 아님).
- 환경변수는 `$env:USERPROFILE` 형식(cmd의 `%VAR%` 아님).
- venv 파이썬은 절대경로로 호출: `& .\.venv\Scripts\python.exe ...`
- 로그 파일은 UTF-16으로 기록될 수 있어 글자 사이 공백처럼 보일 수 있으나,
  이는 인코딩 표기일 뿐 내용은 정상이다.

## 가상환경

- 검증된 venv: 워크스페이스 내 `.venv` (Python 3.14, `-e ".[all,dev]"` 설치됨).
- 소재 경로 pytest + 실제 pymatgen 연산 모두 통과 확인됨.
