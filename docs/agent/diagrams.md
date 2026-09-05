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

The package directory name carries its release date (`Icon-package_07312026.<hash>`), and that date
appears in every directory inside it. `build_diagrams.py` reads it off the package rather than
holding a copy, so a new quarterly release needs no edit. Before switching releases, check whether
the icons already in use changed: if they are byte-identical, the generated `.drawio` files stay
byte-identical too and `--check` still passes, which is what makes the switch safe to do on its own.

A service that shipped recently may be absent from an older package. AWS Interconnect is in
`07312026` and not in `01302026`, which predates its GA.

## Icons that are not AWS assets

They go in `docs/_assets/icons/`, which is gitignored. What gets committed is the diagram with the
icon embedded, never the icon as a file of its own. `build_diagrams.py` names the file it wants and
where to obtain it, so run `--write` and read the error rather than guessing a filename.

The data URI's media type has to match the bytes — `image/png` for PNG, `image/svg+xml` for SVG. Get
it wrong and the export succeeds with a broken-image placeholder.

Each vendor's rules differ, and following them is not optional:

| Vendor | Where | Rules that bear on the diagram |
|---|---|---|
| Microsoft | [Azure architecture icons](https://learn.microsoft.com/azure/architecture/icons/) | Permitted in architecture diagrams, training material and documentation. Keep the product name close to the icon. Do not crop, flip, rotate or reshape. Uniform scaling is not reshaping, so an 18 px source held at 80×80 is fine |
| Google | [Google Cloud icons](https://cloud.google.com/icons) | Core products have unique icons; **everything else uses its category icon plus the product name**, and the name is what distinguishes two products sharing an icon. Check the product icon guide before assuming an icon is missing — Google Cloud NetApp Volumes has no unique icon by design and belongs to Storage |
| NetApp | Obtain from NetApp | The ONTAP 9 badge is a 96 px square and is the one asset held at a size that is not its own, so that it reads as a peer of the 80 px service icons beside it |

**Do not substitute another vendor's mark for a missing icon.** A stand-in attributes the service to
whoever's mark was borrowed. Name the service in a box instead, as the OCI nodes do.

## SVG export is byte-stable, and that is deliberate

draw.io stamps a fresh random element id into every SVG export and uses it twice. Left alone, every
re-export rewrites every SVG, and the files that did not change bury the one that did — the same
failure the fixed `MODIFIED` timestamp prevents in the `.drawio` files. `stabilize_svg()` rewrites
that id to one derived from the file name after each export. Two consecutive `--write --export` runs
now produce identical bytes; if that stops being true, something else in the toolchain became
non-deterministic and the fix belongs in the same place.

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

## Label size — the floor is what a reader sees, not the attribute

`make diagram-fonts` enforces this and is part of `make all`. The numbers live in
`tools/check_diagram_fonts.py`; the standard shared with the sibling repositories is
`~/.kiro/steering/global-document-readability.md`.

A label is displayed at the size it has **after** the image is scaled down to fit the column it sits
in, so a wider canvas makes every label smaller. Two floors, both required:

| Floor | Value | What it stops |
|---|---|---|
| Effective size — `fontSize × min(1, 880 / rendered width)` | **≥ 14px** | A label legible in the editor and not on the page |
| Source `fontSize` | **≥ 16px** | Meeting the first floor by shrinking the canvas rather than growing the text |

880px is the reader's column on GitHub, dev.to and hatenablog. The rendered width comes from the
exported SVG when one exists, not from `pageWidth`: draw.io crops to content and adds `--border`, so
the two differ.

| Canvas width | Required `fontSize` |
|---|---|
| ≤ 880px | 16 |
| 1180px | 19 |
| 1400px | 23 |
| 1550px | 25 |

**Widening the canvas raises the floor**, so empty canvas is not free. When a compliant label stops
fitting, work down this list — shrinking the font is not on it.

1. Fold the label to two lines (two-line maximum; never break mid-word).
2. Move the notes box out of the figure and into body prose as a table. Figure annotations are the
   densest text in any diagram and the least suited to being an image: prose is searchable,
   translatable and reachable by a screen reader, and it stops the same measured figure being kept
   in step by hand in two places.
3. Narrow the canvas toward 880px and stack elements vertically. Height does not compete for width.
4. Split the figure.
5. Abstract — collapse individual resources into the role they play.

### Existing debt

The figures listed in `diagram-font-debt.txt` predate the gate and do not meet the floor. **The file
may only shrink**: an unlisted violation fails, and so does a listed file that now meets the floor,
so fixing a diagram forces its line out.

Fixing them needs one decision that is not a layout decision — whether each figure's in-image notes
box moves into the surrounding prose. Kept in the figure, its longest line dictates the canvas width,
and a wider canvas raises the required font again. Moved out, what remains is relayout.
