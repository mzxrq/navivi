// job_config.json keeps a stop's photos twice: `images` (all of them) and the older `popup_image` (only the first, for the
// Python side). Reading `popup_image` first showed just one photo, and the next save then dropped the others.
export const savedImages = (wp: { images?: string[]; popup_image?: string[] }): string[] =>
  wp.images?.length ? wp.images : wp.popup_image?.length ? wp.popup_image : [];
