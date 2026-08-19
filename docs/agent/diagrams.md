# Regenerating the architecture diagrams

Moved out of `AGENTS.md`, which is loaded on every turn and has a 20,000 B budget. This is needed only
when a diagram changes, so it costs nothing to look up and 2.6 KB to carry. `AGENTS.md` keeps a pointer.

Nothing here is optional detail: the first list is the set of approaches that produce a file which
exports without the icons, which is not visible until someone opens the PNG.

## The only method that works for export

**Generate `.drawio` XML directly with icons embedded as `shape=image;image=data:image/svg+xml,<base64>`
in the cell's `style` attribute.** This is what the sister project's `diagram_builder.py` does.

Things that do NOT work:

| Approach | Problem |
|---|---|
| draw.io MCP `insert_image_vertex` | Icons disappear on CLI export — the tool uses a different embedding method |
| `mxgraph.aws4.*` built-in shapes | 2019 generation icons, wrong colors, not the official AWS asset pack |
| `fillColor=#232F3E` on resource icons | Makes the icon a black filled square |
| `data:image/svg+xml;base64,` (with `;base64`) | draw.io expects `data:image/svg+xml,<base64>` (comma, no `;base64` prefix) |

## Correct workflow

1. **Locate the AWS Architecture Icons asset package** (quarterly release from [aws.amazon.com/architecture/icons](https://aws.amazon.com/architecture/icons/)).
   Default path: `~/Downloads/Icon-package_MMDDYYYY.*/`
2. **Read the SVG, base64-encode, build a data URI**: `data:image/svg+xml,<base64_string>`
3. **Write `.drawio` XML directly** with a Python script using `xml.etree.ElementTree`
4. **Export with draw.io CLI**: `/Applications/draw.io.app/Contents/MacOS/draw.io --export --format png --scale 2 --border 12`
5. **Verify visually** — XML valid does not mean the picture is correct

## Icon style template

```python
style = (
    "sketch=0;html=1;shape=image;verticalLabelPosition=bottom;"
    "verticalAlign=top;labelPosition=center;align=center;"
    f"imageAspect=1;aspect=fixed;fontSize=11;fontColor=#232F3E;"
    f"image={data_uri};"
)
```

## Icon sizes (native, never rescale)

| Asset | File pattern | Size to use |
|---|---|---|
| Service icon | `Arch_<Service>_64.svg` | 80×80 |
| Resource icon | `Res_<Name>_48.svg` | 48×48 |

## Edge style (single color, no variation)

```text
edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=open;endFill=0;strokeColor=#232F3E;strokeWidth=1;
```

## Export commands (macOS)

```bash
# PNG at 2x for blog posts
/Applications/draw.io.app/Contents/MacOS/draw.io --export --format png --scale 2 --border 12 --output out.2x.png src.drawio

# SVG with embedded images for GitHub docs
/Applications/draw.io.app/Contents/MacOS/draw.io --export --format svg --embed-svg-images --border 12 --output out.svg src.drawio
```

## Reference implementation

The sibling repository above has `scripts/diagram_builder.py` with the full compliance system. Here,
a minimal Python script that generates the XML is enough — see `docs/_assets/diagrams/`.
