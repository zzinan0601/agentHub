// Markdown 렌더링. 응답은 md 형식으로 보여야 한다. (요구사항 19)
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js/lib/core'

// 전체 언어를 넣으면 번들이 1MB 를 넘는다. 업무에서 쓸 것만 등록한다.
import bash from 'highlight.js/lib/languages/bash'
import java from 'highlight.js/lib/languages/java'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import python from 'highlight.js/lib/languages/python'
import sql from 'highlight.js/lib/languages/sql'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'

for (const [name, lang] of Object.entries({
  bash,
  java,
  javascript,
  json,
  python,
  sql,
  xml,
  yaml,
})) {
  hljs.registerLanguage(name, lang)
}

const md = new MarkdownIt({
  html: false, // 에이전트가 만든 HTML 을 그대로 실행하지 않는다
  linkify: true,
  breaks: true,
  highlight(code, lang) {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return hljs.highlight(code, { language: lang }).value
      } catch {
        /* 실패하면 아래의 기본 이스케이프로 넘어간다 */
      }
    }
    return md.utils.escapeHtml(code)
  },
})

export function renderMarkdown(text) {
  return md.render(text || '')
}
