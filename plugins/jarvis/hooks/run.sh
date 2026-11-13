# Jarvis 훅을 이 컴퓨터의 파이썬으로 돌린다(hooks.json 이 `sh run.sh gate.py` 로 부른다). 실행 권한이 없어도 된다.
# 맥: python3(맥 기본). 윈도(Git Bash 안): py → python → python3 순서로, 실제로 도는 것을 쓴다
# (python3 이 Microsoft Store 바로가기라 돌지 않는 경우를 건너뛴다).
# 파이썬을 못 찾으면 아무 말 없이 끝낸다(문지기는 고장 나면 막지 않고 통과한다. docs/보안-모델.md).
here=$(dirname "$0")
case "$(uname -s 2>/dev/null)" in
  MINGW*|MSYS*|CYGWIN*)
    for p in py python python3; do
      if command -v "$p" >/dev/null 2>&1 && "$p" -c "import sys" >/dev/null 2>&1 </dev/null; then
        PYTHONUTF8=1 exec "$p" "$here/$1"
      fi
    done
    exit 0 ;;
  *)
    exec python3 "$here/$1" ;;
esac
