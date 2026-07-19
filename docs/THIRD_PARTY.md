# Third-party credits and licenses

GIFmakerAthome depends on the open-source projects below. Thank you to their maintainers and contributors for making this application possible.

This page is an acknowledgement and release checklist, not a substitute for the complete license texts shipped by each project. `requirements.txt` is the authoritative list of direct Python runtime requirements. Before publishing a binary, verify the exact installed package and FFmpeg versions and retain any notices or source offers their licenses require.

## Runtime projects

| Project | How GIFmakerAthome uses it | Declared license |
| --- | --- | --- |
| [Flask](https://github.com/pallets/flask) | Local web application, routing, templates, and responses | BSD-3-Clause |
| [Werkzeug](https://github.com/pallets/werkzeug) | Loopback WSGI server, HTTP utilities, upload-name normalization, and HTTP exceptions | BSD-3-Clause |
| [Beautiful Soup](https://www.crummy.com/software/BeautifulSoup/bs4/) | Discovery of media metadata in supported web pages | MIT |
| [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) | Media probing plus discovery and distribution of the FFmpeg executable | BSD-2-Clause |
| [Pillow](https://github.com/python-pillow/Pillow) | Animated-image probing, frame comparison, and GIF processing | MIT-CMU |
| [Requests](https://github.com/psf/requests) | Validated, streaming HTTP downloads for direct media links and page metadata | Apache-2.0 |
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Extraction and download of media from compatible websites | Unlicense for the Python package; review its own third-party notices for other distribution forms |
| [FFmpeg](https://ffmpeg.org/) | Media inspection, frame extraction, transcoding, resizing, cropping, and animation encoding | Build-dependent: LGPL-2.1+ by default, or GPL when GPL components are enabled |

Flask and the other direct packages also install transitive dependencies. Their package metadata and license files remain authoritative and should be included in a release-software inventory.

## FFmpeg release note

The Windows wheel from `imageio-ffmpeg` includes an FFmpeg executable. FFmpeg explains that enabling GPL components changes the applicable license for that build. The executable currently used by this repository reports both `--enable-gpl` and `--enable-version3`, so that bundled FFmpeg binary is under GPLv3. Release maintainers must re-check this after dependency updates and meet the applicable distribution and corresponding-source requirements.

To inspect the exact executable selected for a release environment:

```powershell
.venv\Scripts\python.exe -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"
.venv\Scripts\python.exe -c "import imageio_ffmpeg, subprocess; subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-version'], check=True)"
.venv\Scripts\python.exe -c "import imageio_ffmpeg, subprocess; subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-L'], check=True)"
```

Refer to [FFmpeg's license and legal considerations](https://ffmpeg.org/legal.html) and the source/distribution information for the exact binary being packaged. This repository invokes FFmpeg as a separate executable and does not claim ownership of FFmpeg or the other projects listed above.
