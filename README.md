# Gemini Demo

`gemini-demo` 通过 OpenAI 兼容的聊天补全接口，把本地音频以 Base64 Data URI 放进多模态 `messages[].content`，调用 Gemini 生成带时间戳的歌词。

当前项目针对 `https://api.shuaiapi.com` 的可用配置是：

- 模型：`gemini-3.1-pro-preview`
- 端点：`/v1/chat/completions`
- 策略：`image-url`
- 媒体类型：`image_url` 内容块，URL 值为 `data:audio/...;base64,...`

这里的 `image_url` 是中转站兼容格式。虽然字段名是 `image_url`，中转站会根据 Data URI 中的 MIME 类型将音频转发给 Gemini 多模态模型。

## 真实接口验证

验证日期：**2026-08-27**。

使用项目中的音频文件：

```text
data/audio/回声 Echoes.mp3
```

文件大小为 6,234,378 bytes，MIME 类型为 `audio/mpeg`。

执行：

```powershell
make run
```

真实请求日志：

```text
[2026-08-27 11:50:38 +08:00] transcription_started: model=gemini-3.1-pro-preview strategy=image-url
[2026-08-27 11:51:55 +08:00] transcription_succeeded: strategy=image-url characters=389
```

接口返回了可解析的歌词，并生成：

```text
data/lyris/回声 Echoes.lrc
```

返回内容包含例如：

```text
[00:53.00] 我们要唱 我们要叫
[00:56.50] 直到地上如同在天上
[01:06.50] 我们是属光明
```

这次验证证明请求确实把音频作为多模态输入发送给了模型，而不是仅发送文本提示。

### 失败配置的原因

此前将模型改为 `gemini-3.1-pro`，并把策略改为 `native-inline`。在本项目的中转站和音频组合下，该请求分别在 **2026-08-27 11:40:20** 和 **11:43:15** 返回 `HTTP 524`，表示上游等待超时。

因此当前可用配置恢复为 `image-url + gemini-3.1-pro-preview`。`native-inline` 和 `input-audio` 仍保留为手动探测选项，但不作为默认方案。

## 请求结构

程序发送到：

```text
POST https://api.shuaiapi.com/v1/chat/completions
```

请求体的关键结构如下：

```json
{
  "model": "gemini-3.1-pro-preview",
  "messages": [
    {
      "role": "user",
      "content": [
        {
          "type": "text",
          "text": "请仔细聆听这首歌曲并转写完整歌词。"
        },
        {
          "type": "image_url",
          "image_url": {
            "url": "data:audio/mpeg;base64,<BASE64_AUDIO>"
          }
        }
      ]
    }
  ],
  "temperature": 1
}
```

认证头：

```text
Authorization: Bearer <API_KEY>
Content-Type: application/json
```

程序会从 `choices[0].message.content` 提取模型输出，并在写文件前检查输出是否为空，或是否明确表示没有收到音频。

## 配置

复制并修改项目根目录的 `.env`：

```dotenv
url=https://api.shuaiapi.com
key=your-api-key
```

当前请求策略和模型写在 [config.toml](config/config.toml)：

```toml
[request]
strategy = "image-url"
model = "gemini-3.1-pro-preview"
```

环境变量可以覆盖本地配置：

```text
GEMINI_BASE_URL
GEMINI_API_KEY
GEMINI_MODEL
GEMINI_REQUEST_STRATEGY
```

`.env` 包含密钥，已被 `.gitignore` 忽略，不应提交到 Git。

## 安装与运行

安装依赖：

```powershell
make install
```

把一个音频文件放到 `data/audio/`。默认目录必须只有一个音频文件，然后运行：

```powershell
make run
```

也可以显式指定文件：

```powershell
uv run python -m gemini_demo "data/audio/回声 Echoes.mp3"
```

指定请求策略：

```powershell
uv run python -m gemini_demo --strategy image-url
uv run python -m gemini_demo --strategy native-inline
uv run python -m gemini_demo --strategy input-audio
```

默认配置必须使用：

```text
image-url + gemini-3.1-pro-preview
```

不要把默认模型改为本中转站当前无法稳定响应的 `gemini-3.1-pro`，也不要把 `native-inline` 设为默认策略，除非已经针对当前接口重新完成真实验证。

## 支持的音频格式

| 扩展名 | MIME 类型 | `input_audio.format` |
| --- | --- | --- |
| `.mp3` | `audio/mpeg` | `mp3` |
| `.m4a` | `audio/mp4` | `m4a` |
| `.wav` | `audio/wav` | `wav` |
| `.flac` | `audio/flac` | `flac` |
| `.ogg` | `audio/ogg` | `ogg` |
| `.aac` | `audio/aac` | `aac` |

`image-url` 策略会把准确 MIME 类型写入 Data URI。音频过大或中转站网关限制请求体时，接口可能返回 `413`、`524` 或其他网关错误；这类情况应先压缩音频或拆分音频后再请求。

## 输出与日志

成功结果写入：

```text
data/lyris/<音频文件名>.lrc
```

日志同时输出到控制台和：

```text
log/log_YYYY-MM-DD.log
```

日志格式：

```text
[YYYY-MM-DD HH:mm:ss +08:00] [级别] [模块] - 具体信息
```

## 项目结构

```text
gemini-demo/
├── config/config.toml       # 请求策略和模型
├── data/audio/              # 输入音频，通常被 Git 忽略
├── data/lyris/              # 生成的 LRC，通常被 Git 忽略
├── data/prompt/lyris.md     # 歌词提示词
├── log/                     # 持久化运行日志
├── src/gemini_demo/
│   ├── client.py            # 多模态请求、HTTP 调用和响应解析
│   ├── cli.py               # 命令行和输出文件
│   ├── config.py            # .env、TOML 和环境变量配置
│   └── logging.py           # 控制台及文件日志
├── Makefile
└── pyproject.toml
```

## 本地检查

本项目的测试不会默认调用远程接口：

```powershell
make test
```

真实接口调用会产生费用，并且可能受中转站负载和网关超时影响。验证多模态是否真正生效，应以日志中的 `transcription_succeeded` 和生成的 `.lrc` 文件为准，而不是只看 HTTP 200。
