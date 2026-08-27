# Gemini Demo

`gemini-demo` 用于验证 OpenAI 兼容中转站的 Gemini 多模态输入能力。当前项目聚焦于把本地音频以内联 Base64 的方式随请求发送给 `gemini-3.1-pro-preview`，并让模型识别歌曲歌词。

本项目不依赖中转站的文件上传接口。音频读取后会被编码为 Base64，再作为 JSON 请求体的一部分发送。这样可以兼容只暴露聊天补全端点、没有独立 Files API 的中转站。

## 实测结论

测试环境：

- 测试日期：2026-08-27
- 中转站：由 `.env` 中的 `url` 配置
- 模型：`gemini-3.1-pro-preview`
- 测试音频：`data/audio/一生爱你.m4a`
- MIME 类型：`audio/mp4`

| 策略 | 请求端点 | 实测结果 | 项目用途 |
| --- | --- | --- | --- |
| `image-url` | `/v1/chat/completions` | 成功识别歌词 | 当前默认主方案 |
| `native-inline` | `/v1beta/models/{model}:generateContent` | 成功识别歌词 | 备用方案 |
| `input-audio` | `/v1/chat/completions` | 请求成功，但中转站没有把 M4A 音频传给模型 | 兼容性探测，不作为当前可用方案 |

自动模式的尝试顺序为：

```text
image-url -> native-inline -> input-audio
```

主方案失败后，程序会自动尝试备用方案。只有模型真正返回歌词时才会写入输出文件；如果模型返回“未上传音频”“无法读取音频”等内容，程序会将其判断为失败并继续尝试下一种策略。

## 当前主方案：`image_url` Data URI

当前默认方案使用 OpenAI 兼容的 `/v1/chat/completions` 端点，并把音频包装为 `image_url` 内容块。

虽然字段名是 `image_url`，但部分多模态中转站会统一解析其中的 Data URI，再根据 MIME 类型把内容转换为 Gemini 可接收的媒体输入。对当前中转站而言，这是已经通过真实音频测试的方案。

### 请求流程

1. 从 `data/audio/` 读取音频字节。
2. 根据扩展名确定 MIME 类型，例如 M4A 使用 `audio/mp4`。
3. 将音频编码为 Base64。
4. 拼接为 `data:audio/mp4;base64,<BASE64>`。
5. 将 Data URI 放入 `image_url.url`。
6. 请求 `/v1/chat/completions`。
7. 从 `choices[0].message.content` 提取歌词。

### image_url 请求结构

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
            "url": "data:audio/mp4;base64,<BASE64_AUDIO>"
          }
        }
      ]
    }
  ],
  "temperature": 0
}
```

### 选择该方案的原因

- 已使用项目中的 M4A 文件完成真实接口测试。
- 可直接复用 OpenAI 兼容的聊天补全端点。
- 不需要中转站实现独立 Files API。
- MIME 类型包含在 Data URI 中，中转站可以据此识别媒体类型。
- 同一种结构也便于中转站统一处理图片、音频、视频或 PDF 等媒体；当前项目代码实际实现和测试的输入类型为音频。

## 备用方案：Gemini 原生 `inline_data`

如果中转站没有正确解析 `image_url` 中的音频 Data URI，程序会尝试 Gemini 原生 `generateContent` 请求。

该方案把 Base64 音频放入 `contents[].parts[].inline_data`，并通过 `mime_type` 明确声明文件类型。当前中转站已经实测能够使用该方案识别同一个 M4A 文件的歌词。

### 请求端点

```text
POST /v1beta/models/gemini-3.1-pro-preview:generateContent
```

### inline_data 请求结构

```json
{
  "contents": [
    {
      "role": "user",
      "parts": [
        {
          "text": "请仔细聆听这首歌曲并转写完整歌词。"
        },
        {
          "inline_data": {
            "mime_type": "audio/mp4",
            "data": "<BASE64_AUDIO>"
          }
        }
      ]
    }
  ]
}
```

请求会同时发送以下认证头，以兼容不同的 Gemini 中转实现：

```text
Authorization: Bearer <API_KEY>
x-goog-api-key: <API_KEY>
Content-Type: application/json
```

### 备用方案的特点

- 使用 Gemini 原生的媒体数据结构，字段语义更明确。
- 不依赖中转站把 `image_url` 特殊转换为音频。
- 需要中转站暴露 `/v1beta/models/{model}:generateContent`。
- 响应结构与 OpenAI 兼容端点不同，歌词从 `candidates[0].content.parts` 中提取。

## `input_audio` 兼容性探测

项目仍保留 OpenAI 风格的 `input_audio` 实现，用于测试其他模型、中转站或音频格式：

```json
{
  "type": "input_audio",
  "input_audio": {
    "data": "<BASE64_AUDIO>",
    "format": "m4a"
  }
}
```

在当前中转站和当前 M4A 文件的组合下，请求本身返回了成功状态，但模型回复没有收到音频。因此，HTTP 200 不代表多模态文件已经被中转站正确转发。

程序会检测以下类型的假成功响应并将策略标记为失败：

- 忘记上传或没有上传音频
- 无法访问或无法读取音频
- 要求用户重新提供音频
- 返回内容为空

## 支持的音频扩展名

当前代码包含以下 MIME 和格式映射：

| 扩展名 | MIME 类型 | OpenAI 格式值 |
| --- | --- | --- |
| `.m4a` | `audio/mp4` | `m4a` |
| `.mp3` | `audio/mpeg` | `mp3` |
| `.wav` | `audio/wav` | `wav` |
| `.flac` | `audio/flac` | `flac` |
| `.ogg` | `audio/ogg` | `ogg` |
| `.aac` | `audio/aac` | `aac` |

这里的“支持”表示程序能够构造对应请求，不代表所有中转站都支持所有格式。是否可用仍应通过真实接口测试确认。

## 环境要求

- Python 3.12 或更高版本
- `uv`
- 能够访问配置的 Gemini 中转站
- 有效的中转站 API Key

## 配置

在项目根目录创建 `.env`：

```dotenv
url=https://api.example.com
key=your-api-key
```

也可以使用环境变量覆盖 `.env`：

```text
GEMINI_BASE_URL
GEMINI_API_KEY
GEMINI_MODEL
```

默认模型为：

```text
gemini-3.1-pro-preview
```

`.env` 已被 `.gitignore` 忽略，不应提交真实 API Key。

## 安装

```bash
uv sync
```

也可以使用 Makefile：

```bash
make install
```

## 使用

### 自动选择可用方案

将一个音频文件放到 `data/audio/`。当目录中只有一个文件时，可以直接运行：

```bash
uv run python -m gemini_demo
```

或：

```bash
make run
```

程序会先使用已经实测可行的 `image-url`，失败后尝试 `native-inline`，最后再使用 `input-audio` 做兼容性探测。

### 指定音频文件

```bash
uv run python -m gemini_demo "data/audio/一生爱你.m4a"
```

当 `data/audio/` 中存在多个文件时，必须显式指定文件路径。

### 指定请求策略

主方案：

```bash
uv run python -m gemini_demo --strategy image-url
```

备用方案：

```bash
uv run python -m gemini_demo --strategy native-inline
```

测试 `input_audio` 兼容性：

```bash
uv run python -m gemini_demo --strategy input-audio
```

输出详细日志：

```bash
uv run python -m gemini_demo --verbose
```

## 输出文件

识别出的歌词保存在：

```text
data/lyris/<音频名称>_<策略名称>_lyrics.txt
```

例如：

```text
data/lyris/一生爱你_image-url_lyrics.txt
data/lyris/一生爱你_native-inline_lyrics.txt
```

`data/lyris/` 中的生成文件会被 Git 忽略，目录通过 `.gitkeep` 保留：

```gitignore
data/lyris/*
!data/lyris/.gitkeep
```

音频文件同样不会提交到仓库：

```gitignore
data/audio/*
!data/audio/.gitkeep
```

## 日志

日志同时输出到控制台和 `log/` 目录，文件名格式为：

```text
log/log_YYYY-MM-DD.log
```

日志行格式为：

```text
[YYYY-MM-DD HH:mm:ss +08:00] [级别] [模块] - 具体信息
```

## 测试

运行本地测试：

```bash
uv run pytest
```

或：

```bash
make test
```

默认测试不会调用远程接口。

### 真实接口集成测试

PowerShell：

```powershell
$env:RUN_GEMINI_INTEGRATION = "1"
uv run pytest -m integration
```

Bash：

```bash
RUN_GEMINI_INTEGRATION=1 uv run pytest -m integration
```

集成测试会读取：

- `.env` 中的中转地址和密钥
- `data/audio/` 中的 M4A 文件
- `image-url` 主方案

测试会检查返回内容长度，并验证歌词中包含预期文本。运行该测试会产生真实 API 请求和相应费用。

## 项目结构

```text
gemini-demo/
├── data/
│   ├── audio/               # 本地音频，文件被 Git 忽略
│   └── lyris/               # 生成歌词，文件被 Git 忽略
├── log/                     # 按日期保存运行日志
├── src/gemini_demo/
│   ├── cli.py               # CLI、策略回退和文件输出
│   ├── client.py            # 请求构造、接口调用和响应解析
│   ├── config.py            # .env 与运行配置
│   └── logging.py           # 日志格式和持久化
├── test/
│   ├── test_client.py       # 请求结构和解析单元测试
│   └── test_integration.py  # 真实中转接口测试
├── .env                     # 本地配置，不提交
├── Makefile
└── pyproject.toml
```

## 实现位置

- 多模态请求和三种策略：`src/gemini_demo/client.py`
- 自动回退顺序：`src/gemini_demo/cli.py`
- 音频、歌词和日志目录配置：`src/gemini_demo/config.py`
- 真实接口测试：`test/test_integration.py`
