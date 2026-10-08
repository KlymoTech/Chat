"""Add only the verified Figma font packages; preserve all other locked metadata."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FONT_HASHES = {
    'jetbrains-mono': 'sha512-F32xpS2NsGYoQi2ADSkKTgpJj7ozajsGgDJ8woTnqjmIB+dxDIqImjl4pXZVEExu8UFZ2ndhmX18EBS/hdz3Lw==',
    'plus-jakarta-sans': 'sha512-/l/4r0yyWK9JzAlmA0LiYgGgmJe/Gswt4jTJEzr5QhJfwMbvJZDmYWyW0M4X7yCK69BajMVlV/Lx8g7WDc1+sw==',
    'space-grotesk': 'sha512-2IxmvfB08i9vnGB3Ym/AXvhRE+8XOjWMXIyDum03c+tPwH0FUoMNQfGpU8NXPxjbws0Vvss3AH0Zqt4oJBBAdw==',
}
manifest = ROOT / 'frontend/package.json'
lockfile = ROOT / 'package-lock.json'
package = json.loads(manifest.read_text())
lock = json.loads(lockfile.read_text())
for font, integrity in FONT_HASHES.items():
    name = f'@fontsource-variable/{font}'
    package['dependencies'][name] = '5.3.0'
    lock['packages']['frontend']['dependencies'][name] = '5.3.0'
    lock['packages'][f'node_modules/{name}'] = {
        'version': '5.3.0',
        'resolved': f'https://registry.npmjs.org/{name}/-/{font}-5.3.0.tgz',
        'integrity': integrity,
        'license': 'OFL-1.1',
        'funding': {'url': 'https://github.com/sponsors/ayuhito'},
    }
package['dependencies'] = dict(sorted(package['dependencies'].items()))
lock['packages']['frontend']['dependencies'] = dict(sorted(lock['packages']['frontend']['dependencies'].items()))
lock['packages'] = dict(sorted(lock['packages'].items()))
manifest.write_text(json.dumps(package, indent=2) + '\n')
lockfile.write_text(json.dumps(lock, indent=2) + '\n')
main = ROOT / 'frontend/src/main.tsx'
text = main.read_text()
imports = '\n'.join(f"import '@fontsource-variable/{font}';" for font in FONT_HASHES) + '\n'
if "import '@fontsource-variable/jetbrains-mono';" not in text:
    anchor = "import '@/theme/saas-bot.css';"
    if text.count(anchor) != 1:
        raise RuntimeError('Expected exactly one SaaS Bot stylesheet import')
    main.write_text(text.replace(anchor, imports + anchor))
