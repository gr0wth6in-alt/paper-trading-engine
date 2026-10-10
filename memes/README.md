# Local artwork

Put PNG, JPG/JPEG, WebP or GIF files in `profit`, `loss`, or `entry` below this folder.
Files replace original frogs only in the category where valid images exist.

- Up to 5 MiB per image; first 50 valid names in alphabetical order are listed.
- No SVG, symlink/junction paths, remote URLs, or uploads through the API.
- Browser decoding is capped at 24 megapixels. Smaller images load faster.
- The whole image is fitted without cropping; transparent images work well.
- GIFs are rendered as a single still frame for export and splash.
- Existing artwork refreshes when opening/shuffling a card. Entry artwork refreshes every
  minute and after a fill splash, so it is already decoded before the next fill.
- Only use art you have permission to share. Private text embedded in an image is not removed.

Set `PAPER_MEMES_DIR` to use another folder. Relative paths resolve from the project directory
when launched with start.cmd. Authentication protects both `/api/v1/memes` and image downloads.
There is no public static mount for this folder.