// Server-sent events: feed it the text as it arrives, get back the `data:` payload of every event that is complete.
export class SseParser {
  private partial = "";
  private data: string[] = [];

  push(text: string): string[] {
    // a \r at the very end may be the first half of \r\n, so it waits for the next chunk
    const text_ = this.partial + text;
    const held = text_.endsWith("\r") ? "\r" : "";
    const lines = (held ? text_.slice(0, -1) : text_).replace(/\r\n?/g, "\n").split("\n");
    this.partial = lines.pop()! + held;

    const out: string[] = [];
    for (const line of lines) {
      if (line === "") {
        if (this.data.length) out.push(this.data.join("\n"));
        this.data = [];
      } else if (line.startsWith("data:")) {
        this.data.push(line.slice(5).replace(/^ /, ""));
      }
    }
    return out;
  }

  // The stream ended: an event the server did not close with a blank line still counts.
  flush(): string[] {
    const out = this.push("\n\n");
    this.partial = "";
    return out;
  }
}
