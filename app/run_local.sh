#!/bin/bash
cd "$(dirname "$0")" || exit 1
PORT=8801
rm -f local.log local_out.txt
npx wrangler dev --local --port "$PORT" --ip 127.0.0.1 > local.log 2>&1 &
DEV=$!
for i in $(seq 1 60); do
  curl -sf --max-time 5 "http://127.0.0.1:$PORT/api/health" -o /dev/null 2>/dev/null && break
  sleep 2
done

# 一份共享词表:三条 gate 臂之间【只许差一个变量】
W='[{"text":"send","start":0,"end":90,"confidence":0.99,"word_is_final":true},
    {"text":"five","start":100,"end":190,"confidence":0.99,"word_is_final":true},
    {"text":"hundred","start":200,"end":290,"confidence":0.99,"word_is_final":true},
    {"text":"US","start":300,"end":390,"confidence":0.99,"word_is_final":true},
    {"text":"dollars","start":400,"end":490,"confidence":0.99,"word_is_final":true},
    {"text":"to","start":500,"end":590,"confidence":0.99,"word_is_final":true},
    {"text":"Alice","start":600,"end":690,"confidence":0.99,"word_is_final":true}]'
# 只把 Alice 的置信度压到 0.71,其余逐字相同
WLOW=$(printf '%s' "$W" | sed 's/{"text":"Alice","start":600,"end":690,"confidence":0.99/{"text":"Alice","start":600,"end":690,"confidence":0.71/')

gate () {  # $1=标签 $2=amount $3=words $4=format_turns片段
  echo "### gate · $1"
  curl -s -X POST "http://127.0.0.1:$PORT/api/gate" -H 'content-type: application/json' \
    -d "{$4\"proposal\":{\"action\":\"transfer\",\"arguments\":{\"amount\":\"$2\",\"currency\":\"USD\",\"to\":\"Alice\"}},\"words\":$3}" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print(" ", d.get("outcome") or d.get("error"), "| reasons:", d.get("reasons"), "| matched:", sorted((d.get("evidence") or {}).get("matched",{})))'
}

{
echo "### /api/health"; curl -s "http://127.0.0.1:$PORT/api/health"; echo
echo "### / 静态资源"; curl -s -o /dev/null -w "  HTTP %{http_code} · %{size_download} B\n" "http://127.0.0.1:$PORT/"
gate "正例:说了 five hundred US dollars to Alice" 500  "$W"    '"format_turns":false,'
gate "篡改:只把 amount 改成 5000"                  5000 "$W"    '"format_turns":false,'
gate "听错:只把 Alice 的置信度压到 0.71"            500  "$WLOW" '"format_turns":false,'
gate "不声明 format_turns(其余与正例逐字相同)"       500  "$W"    ''
# 🩸 这里【曾经】写着「上限已临时压到 2,第 3 次必须 429」—— 那是假的:
#    没有任何压低上限的机制,committed 值就是 main.py 的 DAILY_TOKEN_LIMIT。
#    三次调用会全部 200 OK,于是脚本的叙述与它自己的输出互相矛盾 ——
#    跑这个脚本的人第一眼看到的就是它在说谎。
# 🔑 数从源码现取,不写字面量:写死一个数,它下次改动后当场变成第二条假话。
LIMIT=$(sed -n 's/^DAILY_TOKEN_LIMIT *= *\([0-9]*\).*/\1/p' worker/main.py | head -1)
echo "### /api/token ×3 —— 该看的是配额计数器,不是 429"
echo "    期望:三次全 200 OK,响应里 quota.issued 连续 +1 三次,quota.limit == ${LIMIT:-?}"
echo "    ⚠ 起点不一定是 1 —— 本地 DO 状态若从上一轮留存下来,当天计数会接着往上走。"
echo "    429 只在当天真发满 ${LIMIT:-?} 次时出现;本脚本【不】制造它,也不假装制造。"
for n in 1 2 3; do
  printf '  第 %s 次: ' "$n"
  curl -s -w ' [HTTP %{http_code}]\n' "http://127.0.0.1:$PORT/api/token" | head -c 300
done
} > local_out.txt 2>&1
kill "$DEV" 2>/dev/null; wait "$DEV" 2>/dev/null
cat local_out.txt
