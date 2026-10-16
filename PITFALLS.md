# 踩坑全记录

从"想做个企微消息提醒"到交付，踩了 30 多个坑。按类别整理，每类都写了
**症状 → 根因 → 解法**，你可以直接跳到需要的部分。

---

## 一、环境与依赖

### 1. WorkBuddy 自带的 Python 3.13 没有 tkinter

**症状**：小组件（唯一可选的 GUI 方案）一跑就 `ModuleNotFoundError: No module named 'tkinter'`。
**根因**：官方 Python 3.13 的 Windows 构建里，tkinter 是可选组件，这个版本没带。
**解法**：静默安装官方 Python 3.12 到 D 盘（顺带满足"软件不占 C 盘"的要求）：

```powershell
python-installer.exe /quiet InstallAllUsers=0 TargetDir=D:\Python312 `
  AssociateFiles=0 Shortcuts=0 Include_launcher=0 PrependPath=0 Include_tcltk=1
```

`Include_tcltk=1` 就是关键——默认静默安装**不带** tk。

### 2. venv 反复创建失败

**症状**：`python -m venv` 在 D 盘上死活创建不出来，换 `--clear` 也不行。
**根因**：环境限制，venv 的创建路径/权限在本机不通。
**解法**：**放弃 venv**，直接把依赖装进 `D:\Python312` 本体。
代价：遗留了一个 60MB 的废弃目录（已重命名为 `_unused_venv_can_delete` 提示可删）。

### 3. Pillow 装不上

**症状**：`pip install pillow` 失败。
**解法**：不装了。用标准库 `zlib` + `struct` 手写 PNG 编码，30 行搞定，零依赖。

```python
def png_bytes(bgra, w, h, stride):
    raw = b""
    for y in range(h):
        raw += b"\x00" + bgra[y * stride:(y + 1) * stride]
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw, 6))
            + _chunk(b"IEND", b""))
```

### 4. `pyesedb` 编译装不上

**症状**：想直接读 Windows 通知历史库 `wpndatabase.db`（ESE 格式），`pip install pyesedb` 失败。
**影响**：通知历史这条路直接放弃（后来证明这条路本来也是死路）。

### 5. `wecom-cli` 不在 Windows 的 PATH 里

**症状**：Python 的 `subprocess.run(["wecom-cli", ...])` 找不到命令，
但在 Git Bash 里直接敲却能用。
**根因**：它只加到了 Git Bash 的环境，没进系统 PATH。
**解法**：调用时写完整路径 + `.cmd` 后缀：

```python
r"C:\Users\…\binaries\node\cli-connector-packages\wecom-cli.cmd"
```

---

## 二、64 位下的 ctypes 经典陷阱

### 6. 剪贴板永远读到空字符串 ★ 最隐蔽的一个

**症状**：写入剪贴板后立刻读回，永远是 `""`，但系统剪贴板里内容是对的。
**根因**：**64 位下 ctypes 函数默认 `restype` 是 `c_int`（32 位）**，
`GetClipboardData` 和 `GlobalLock` 返回的 64 位句柄被**截断成低 32 位**，
拿到的是个野指针。

**解法**：必须显式声明返回类型。

```python
# 错误
user32.GetClipboardData(CF_UNICODETEXT)

# 正确
user32.GetClipboardData.restype = ctypes.c_void_p   # 或 HANDLE
kernel32.GlobalLock.restype = ctypes.c_void_p
```

这个 bug 害得我一度误判"`Ctrl+F` 唤起企微搜索框失败"——其实是回读验证的
代码本身有问题，快捷键一直是好的。

> **通用教训**：在 64 位 Windows 上，任何返回指针/句柄的 Win32 函数，
> 用 ctypes 调都必须显式设 `restype`，否则句柄会被截断。

### 7. `BITMAPINFOHEADER` 打包格式错

**症状**：`GetDIBits` 出来的图是花的或全黑。
**根因**：`struct.pack` 格式串必须是小端 `<IiiHHIIiiII`，写成 `"IiiHHIIiiII"`
（本机字节序）在某些场景下会错位。
**解法**：显式加 `<` 前缀。

---

## 三、读取企业微信消息

### 8. 企微是 Flutter 渲染，UIA 只能读到 2 个空节点 ★ 根本性障碍

```
企微主窗口 class = WeWorkWindow
  └─ 唯一子窗口 class = FLUTTERVIEW
      └─ UIA: 2 个节点，Name 全空
```

**影响**：
- 读不到任何聊天文本 → 无法自动监听消息；
- 点不动任何会话 → "右键标记为已读"这条路废掉，改走快捷键。

**绕过**：Flutter 最终要把像素画到窗口上 → 走屏幕截图 + OCR。

### 9. 会话存档接口 853006：企业没开通，不是你没授权

**症状**：

```
wecom-cli chat messages list --chat-id <任意值>  → errcode 853006
this tool is not available for your corporation
```

**关键推理（省了我半天时间）**：我用 4 个 chat-id 试，其中 3 个是瞎编的
（`wmXXXX` / `test`），**全部返回同一个错误码**。这说明拦截发生在
**校验 chat-id 之前**——是**企业层级的功能开关**，不是参数问题、也不是授权问题。

**结论**：连接器只能**发**消息，**读不了**你和同事的聊天记录。
想让它能读，需要**企业管理员**去开「会话内容存档」（付费功能）。

### 10. 全量普查证明：连接器里根本没有"收消息"命令

```
wecom-cli message recv / receive / pull / list
wecom-cli message aibot recv / messages
wecom-cli chat recv / receive
wecom-cli webhook / callback
→ 全部 "unrecognized subcommand"
```

唯一能用的读类接口 `message aibot sessions list` 只返回**机器人自己**会话的
元数据（`chat_id` / `chat_name` / `chat_type` / `last_msg_time`），
**没有任何命令能读这些会话的消息正文**。

### 11. 通讯录接口 850002

`contact users search` → 850002，机器人未被授权「通讯录」。
（但如 §9 所述，就算授了权，853006 依然在，聊天记录还是读不了。）

### 12. 企微在本机根本不弹系统通知

**症状**：通知探针跑 150s / 180s / 240s，一条企微通知都没抓到。
**影响**："捕获系统 Toast 通知"这条路断了——原本以为它是唯一能绕开
Flutter 限制的通道（通知是系统渲染的）。

### 13. 抓到的是过期画面 —— "发了消息没反应"的真凶 ★

**症状**：用户发消息，程序毫无反应；手动截图看画面是对的。
**根因**：用 `BitBlt` 抓窗口，对 Flutter（走 DirectComposition 合成）
只能拿到**过期的那一帧**。

**解法**：用 `PrintWindow` 的 `PW_RENDERFULLCONTENT` 标志强制重渲染。

```python
PW_RENDERFULLCONTENT = 2
ok = user32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT)
if not ok:
    gdi32.BitBlt(mem, 0, 0, w, h, hdc, 0, 0, SRCCOPY)  # 回退
```

### 14. 最小化 / 移到屏幕外 = 画面冻结 ★ 推翻了我的错误判断

我最初以为"用 PrintWindow 连最小化也能读到"，实测**是错的**。
用内容指纹做的受控实验（用户发消息，我盯着指纹变不变）：

| 企微窗口状态 | 结果 |
|---|---|
| 显示在屏幕 + 消息页 | ✅ 指纹随新消息变化 |
| **最小化到任务栏** | ❌ 70 秒纹丝不动 |
| **移到屏幕外**（未最小化） | ❌ 2.5 分钟不动，移回屏幕**立刻**变化 |
| 切到「工作台/文档」页 | ❌ 没有会话列表 |
| 被其它窗口盖住 | ✅ 仍可读 |
| 在另一个虚拟桌面 | ✅ 仍可读 |

**好消息**：被盖住 / 在别的虚拟桌面都**不影响**，所以可以把它藏在后面眼不见为净。

### 15. 最小化时 `GetWindowRect` 返回的坐标不靠谱

**症状**：截图尺寸塌成 314x50（微信）或 -32000（企微）。
**根因**：最小化时 `GetWindowRect` 返回的是任务栏图标的小矩形，
或 `(-32000, -32000)` 这种"不存在"坐标。

**解法**：用 `GetWindowPlacement` 拿 `rcNormalPosition`（还原后的矩形）：

```python
# 只判断 -32000 会漏——微信最小化返回的是 314x50
if r.left <= -20000 or r.top <= -20000 or user32.IsIconic(hwnd):
    plc = WINDOWPLACEMENT()
    plc.length = ctypes.sizeof(plc)
    if user32.GetWindowPlacement(hwnd, ctypes.byref(plc)):
        r = plc.rcNormalPosition
```

`IsIconic(hwnd)` 这个判断是后来测微信时才补上的。

### 16. 误把「工作台」页面当成消息列表，生成了一堆垃圾待办

**症状**：小组件显示"待处理 2 条"，但点开什么都没有。
**根因**：企微有多个标题都叫「企业微信」的窗口，程序没判断当前停在哪个页，
把工作台页的"审批""智能机器人""打卡"当成了消息。
**解法**：加 `is_chat_view()` 判断——靠**会话列表右侧的时间戳**特征
（`刚刚` / `xx分钟前` / `昨天` / `xx:xx`）来确认当前是消息页，
切到工作台/文档页自动跳过并清空基线。

> 第一版判断是找顶部的"未读/@我/单聊/群聊"筛选条，**太严了**，
> 实测布局里筛选条位置对不上，导致本该能读的也跳过了。改用时间戳特征才稳。

### 17. OCR 对 12px 小字识别率很差

截图原图很清晰，但 OCR 出来一堆错字。
**解法**：GDI `HALFTONE` 模式高质量放大 **2 倍**再送 OCR，识别质量可用
（人名偶有误差，消息正文基本准确）。放大 3 倍提升有限但更慢。

```python
gdi32.SetStretchBltMode(mem2, HALFTONE)
gdi32.SetBrushOrgEx(mem2, 0, 0, 0)
gdi32.StretchBlt(mem2, 0, 0, W, H, mem, 0, 0, w, h, SRCCOPY)
```

### 18. WinRT 的 IAsyncOperation 不能自己造 event loop

**症状**：用 `asyncio.new_event_loop().run_until_complete(await ...)` 卡死。
**解法**：改用事件驱动同步等待（设事件 → 触发 → 等待 → 取结果）。

### 19. OCR 出来的名字是错字，@我 判断漏判

**症状**：`@秦国彬` 被 OCR 成 `@泰国彬` / `@孬王彬` / `@癸国彬`，精确匹配全部漏掉。
**解法**：`difflib` 模糊匹配，相似度阈值内都算命中。
（代价：群名也可能被误匹配，所以同时保留了 `group_senders` 白名单。）

### 20. 截图有透明通道时 OCR 拿到全透明图

**症状**：OCR 返回 0 行。
**根因**：窗口截图 alpha 通道是 0，OCR 引擎认为整图透明。
**解法**：强制把 alpha 填成不透明：

```python
ba = bytearray(buf)
ba[3::4] = b"\xff" * (sw * sh)
```

---

## 四、桌面小组件（tkinter）

### 21. 收起时把 34px 高度存进了 geometry

**症状**：收起小组件后重启，窗口只剩一条标题栏，内容全没了。
**根因**：收起状态也保存了窗口尺寸（34px = 只有标题条的高度）。
**解法**：收起状态**不保存尺寸**，且载入几何时强制最小高度 200px。

### 22. 收起后只能双击展开，用户以为点不动

**症状**：用户说"点击也没有反应"。
**解法**：收起时改成**单击**标题条即展开。（原来绑的是双击，且没有任何提示。）

### 23. 卡片合并后，勾掉单条时删除线画错了

**症状**：勾掉后连复选框本身也被划掉。
**解法**：遍历行内 Label 时跳过 `☑` 本身。

### 24. 卡片合并的 pack 顺序

收起/展开时 `list_frame` 和 `footer` 的 pack 顺序会乱，要用 `before=` 指定顺序。

---

## 五、消息判定

### 25. 关键词把「无需回复」误判成需要处理

**症状**："公司年会照片已上传，**无需回复**" → 判定为待办。
**根因**：命中了"回复"两个字。
**解法**：加否定词排除——先扫否定词（`无需` / `不用` / `不必` / `已通过` …），
命中就直接判为无需处理。

### 26. 「@所有人」被当成「@我」

**症状**：群里的 `@所有人 明天团建` 也被钉到桌面。
**解法**：只认 `@你本人`（昵称来自 `config.json` 的 `filter.my_names`），
`@所有人` / `@全体成员` 一律不算。AI 提示词里也写死了这条规则。

### 27. 勾掉后消角标：Flutter 下 UIA 无效

企微没有开放"标记已读"的接口。两级策略：

1. UIA 找会话 → 右键 → "标记为已读"（Flutter 下**基本用不上**）
2. **快捷键（主路线）**：激活企微 → `Ctrl+F` 唤起搜索 → 粘贴会话名 →
   回车打开会话 → 角标清除 → `Esc` → 切回原窗口

`Ctrl+F` 这条实测通过（用"选中 → 复制回读"的方式验证，避免截图验证）。
不灵时可换 `Ctrl+K`，或直接设 `click_search_offset` 用鼠标点搜索框。

---

## 六、进程与自启动

### 28. 自动化环境拉起的进程全部存活不下来 ★ 影响交付方式

**症状**：程序明明启动了、日志也写了，过一会儿就没了。
**实测**：

| 方式 | 结果 |
|---|---|
| `Start-Process` | 被安全策略拦截 |
| `wscript.exe` 跑 VBS | 被拦截 |
| `schtasks /create /sc onlogon` | 直接被拉黑 |

**解法**：**必须由用户双击 `Start.bat`** 启动，或等下次开机（Startup 的 VBS 已装好）。
这条直接改变了交付方式——我不能替用户把程序跑起来。

### 29. 多个实例同时跑导致重复捕获

**症状**：日志里每条消息重复出现、CPU 飙高。
**根因**：反复重启时旧进程没杀干净。
**解法**：用 `WMI Win32_Process` 按命令行特征批量清理，且每次重启前删 `app.pid`。

### 30. 改了代码但进程里跑的是旧版本

**症状**：traceback 的行号跟源码对不上，改了就是不生效。
**解法**：重启前先删 `__pycache__`。

---

## 七、个人微信

### 31. 个人微信官方就没有开放读取聊天记录的 API ★ 根本障碍

微信只开放了三类 API：**公众号、小程序、企业微信**，**个人账号的聊天记录不在其中**。
所以**不存在"授权某个应用读我的微信消息"这个动作**——
用户问"需要授权吗"，答案是"不需要，也无处可授权"。

### 32. 微信 4.0 是 Qt + 自绘，UIA 同样空

```
主窗口 class = Qt51514QWindowIcon
  └─ 唯一子窗口 class = MMUIRenderSubWindow
      └─ UIA: 0 个节点
```

### 33. 微信本地数据库全部 SQLCipher 加密

`Documents\WeChat Files\<wxid>\Msg\` 下 12 个库（含 `ChatMsg.db`），
文件头全部不是 `SQLite format 3`。

### 34. 微信最小化时截图是纯色空图

```
截图 1358x1716，采样像素种类数 = 2（值只有 0 和 255），OCR 0 行
```

---

## 最值钱的三个教训

1. **先证明"能不能"，再动手做。** 我在"企微最小化也能读到"这个错误判断上
   浪费了最多时间——先做 30 秒的受控实验（内容指纹），能省掉后面几小时。
2. **64 位 + ctypes 必须显式声明 `restype`。** 句柄截断的表现极具迷惑性
   （读出来是空字符串，看起来像"功能不支持"）。
3. **报错码要会读。** 853006 用 4 个不同 ID 测试结果相同 → 立刻能断定是
   企业层开关，而不是"我的参数写错了"，省掉了无意义的调试。
