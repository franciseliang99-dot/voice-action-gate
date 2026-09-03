#!/bin/bash
# 复核:仓里的 cover.png / slides.pdf 确实是由【同仓的 src/*.html】渲出来的。
#
# 🔴 为什么需要这道检查 —— 纯文本工具对这两种格式【读不进去】:
#    PNG 是栅格,里面根本没有文字;PDF 的文字在 FlateDecode 流里,
#    裸字节扫描够不到。⇒ 仓里其余文件能靠【读】来核实的东西,
#    这两个文件靠读核实不了。
#    本脚本把它们重新拴回一个读得到的对象:src/ 里的纯文本 HTML。
#
# ⚠ 诚实边界:它证明的是「产物 = 渲染(仓里这份源)」,
#    **不证明**源本身是对的 —— 它只保证你看到的这个二进制,就是这份文本渲出来的。
#    也**不覆盖**任何不是这样生成的二进制(截屏、录屏、外来图),那些照旧是盲区。
set -u
cd "$(dirname "$0")" || exit 3
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
[ -x "$CHROME" ] || { echo "✗ 找不到 Chrome —— 判不出来(exit 3),绝不当作通过"; exit 3; }

T=$(mktemp -d) || exit 3
trap 'rm -rf "$T"' EXIT
rc=0

"$CHROME" --headless --disable-gpu --hide-scrollbars --window-size=1920,1080 \
  --screenshot="$T/cover.png" "file://$PWD/src/cover.html" >/dev/null 2>&1
"$CHROME" --headless --disable-gpu --no-pdf-header-footer \
  --print-to-pdf="$T/slides.pdf" "file://$PWD/src/slides.html" >/dev/null 2>&1

for f in cover.png slides.pdf; do
  [ -s "$T/$f" ] || { echo "✗ $f 重渲失败或为空 —— 判不出来"; rc=3; continue; }
done
[ "$rc" = 3 ] && exit 3

if cmp -s cover.png "$T/cover.png"; then
  echo "✅ cover.png   逐字节 = 渲染(src/cover.html)"
else
  echo "🔴 cover.png   与 src/cover.html 的渲染结果【不一致】"; rc=1
fi

# PDF:Chrome 每次写入不同的 /CreationDate /ModDate(实测唯一差异,共 8 字节)⇒ 归一化后比。
python3 - "$T/slides.pdf" <<'PY'
import io,re,sys
norm=lambda p: re.sub(rb"/(CreationDate|ModDate)\s*\(D:[^)]*\)", b"/X()",
                      io.open(p,"rb").read())
a,b = norm("slides.pdf"), norm(sys.argv[1])
if a==b: print("✅ slides.pdf  归一化后逐字节 = 渲染(src/slides.html)"); sys.exit(0)
print(f"🔴 slides.pdf  与 src/slides.html 的渲染结果【不一致】(差 {sum(1 for i in range(min(len(a),len(b))) if a[i]!=b[i])} 字节,长度 {len(a)} vs {len(b)})")
sys.exit(1)
PY
[ $? -ne 0 ] && rc=1

echo
[ "$rc" = 0 ] && echo "verify: PASS —— 两个二进制产物都可从仓内纯文本源复现" \
             || echo "verify: FAIL(exit $rc)—— 产物与源脱钩,这两个二进制现在无人担保"
exit $rc
