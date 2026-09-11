import { invoke } from '@tauri-apps/api/core';
import { appDataDir, join } from '@tauri-apps/api/path';

/**
 * Triggers ComfyUI Wan 2.2 Image-to-Video generation using the Python backend.
 * @param imagePath The local path to the input image.
 * @param prompt The English motion prompt.
 * @returns The local path to the generated video file.
 */
export async function generateComfyUiVideo(imagePath: string, prompt: string): Promise<string> {
    const appData = await appDataDir();
    const outputPath = await join(appData, `comfyui_video_${Date.now()}.mp4`);
    
    const payload = JSON.stringify({
        image_path: imagePath,
        output_path: outputPath,
        duration: 5.0,
        prompt: prompt
    });

    const res = await invoke<string>("run_python_blueprint", { 
        action: "generate_video", 
        payload 
    });
    
    const parsed = JSON.parse(res);
    if (!parsed.success) {
        throw new Error(parsed.error || "Generation failed");
    }
    
    return parsed.video_path;
}
