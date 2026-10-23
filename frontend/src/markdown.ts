import MarkdownIt from "markdown-it";
import DOMPurify from "dompurify";

const renderer = new MarkdownIt({ html: false, linkify: false, breaks: false });
export function renderMarkdown(value: string) {
  return DOMPurify.sanitize(renderer.render(value), { FORBID_TAGS: ["img"] });
}
