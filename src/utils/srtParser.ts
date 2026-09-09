export interface ParsedSubtitle {
    id: number;
    startTime: number;
    endTime: number;
    text: string;
  }
  
  export function parseSRT(srtContent: string): ParsedSubtitle[] {
    const blocks = srtContent.trim().split(/\r?\n\s*\r?\n/);
    
    return blocks.map((block) => {
      const lines = block.split(/\r?\n/);
      const id = parseInt(lines[0], 10);
      const timeLine = lines[1];
      
      // Join the remaining lines as the actual subtitle text
      const text = lines.slice(2).join('\n');
  
      // SRT time format: 00:00:01,000 --> 00:00:04,000
      const [startStr, endStr] = timeLine.split(' --> ');
  
      const parseTime = (timeStr: string) => {
        if (!timeStr) return 0;
        const [hours, minutes, rest] = timeStr.split(':');
        const [seconds, millis] = rest.split(',');
        return (
          parseInt(hours, 10) * 3600 +
          parseInt(minutes, 10) * 60 +
          parseInt(seconds, 10) +
          parseInt(millis, 10) / 1000
        );
      };
  
      return {
        id,
        startTime: parseTime(startStr),
        endTime: parseTime(endStr),
        text
      };
    });
  }