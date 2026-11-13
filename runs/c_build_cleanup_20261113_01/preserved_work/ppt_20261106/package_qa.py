import hashlib
import json
from pathlib import Path
import re
import zipfile
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[2]
source = root / 'docs/deliverables/组会汇报_边界修复与dev准备_20261030.pptx'
final = root / 'docs/deliverables/组会汇报_两例五组实验_20261106.pptx'
data_path = root / 'docs/deliverables/两例五组实验_20261106_source/report_data.json'
data = json.loads(data_path.read_text(encoding='utf-8-sig'))
digest = lambda value: hashlib.sha256(value).hexdigest()
def inspect(file):
    with zipfile.ZipFile(file) as package:
        names = package.namelist()
        slide_paths = sorted([name for name in names if re.fullmatch(r'ppt/slides/slide\d+\.xml', name)], key=lambda name: int(re.search(r'(\d+)\.xml$', name).group(1)))
        ns = {'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}
        tables = [i for i, name in enumerate(slide_paths, 1) if ET.fromstring(package.read(name)).findall('.//a:tbl', ns)]
        return {
            'slides': len(slide_paths),
            'table_owner_slides': tables,
            'masters': len([name for name in names if re.fullmatch(r'ppt/slideMasters/slideMaster\d+\.xml', name)]),
            'layouts': len([name for name in names if re.fullmatch(r'ppt/slideLayouts/slideLayout\d+\.xml', name)]),
            'media_sha256': sorted(digest(package.read(name)) for name in names if name.startswith('ppt/media/')),
            'artwork_sha256': sorted(digest(package.read(name)) for name in names if name.startswith('ppt/media/') and len(package.read(name)) > 67),
            'notes': len([name for name in names if re.fullmatch(r'ppt/notesSlides/notesSlide\d+\.xml', name)]),
        }
before, after = inspect(source), inspect(final)
source_hashes_valid = all(digest((root / relative).read_bytes()) == expected for relative, expected in data['source_hashes'].items())
report = {
    'final_path': str(final),
    'final_sha256': digest(final.read_bytes()),
    'byte_count': final.stat().st_size,
    'source_template_sha256': digest(source.read_bytes()),
    'final_package': after,
    'source_package': before,
    'all_source_hashes_match': source_hashes_valid,
    'source_count': len(data['source_hashes']),
    'shared_template_artwork_preserved': set(before['artwork_sha256']) == set(after['artwork_sha256']),
    'export_media_normalization': 'Artifact Tool retained all four substantive PNG/SVG artwork assets byte-for-byte. It omitted the source deck 67-byte one-pixel PNG fallback for the retained SVG. Original and final slides were visually compared.',
    'native_tables_verified': after['table_owner_slides'] == [3, 4, 6, 7],
    'all_slides_have_notes': after['notes'] == after['slides'] == 10,
    'visual_review': {
        'source_slides_reviewed': {'20261029': list(range(1, 11)), '20261030': list(range(1, 11))},
        'final_slides_rendered_and_reviewed': list(range(1, 11)),
        'final_revision_changed_slides_reviewed': [5, 8, 9],
        'observed_clipping_or_overlap': [],
        'template_match': 'Preserved slide size, masters/layouts, university artwork, blue header, gray campus background, page furniture, Microsoft YaHei font and reference text sizes.',
        'native_powerpoint_opened': False,
    },
    'finalizer_receipt': 'work/ppt_20261106/final_revision3.pptx.validation.json',
    'final_render_directory': 'work/ppt_20261106/final_render',
    'facts_independently_checked': 'pydicom_env agent: all ten verdicts/resources/prediction hashes, five arm costs, release counts and source hashes',
}
assert source_hashes_valid
assert report['shared_template_artwork_preserved']
assert report['native_tables_verified']
assert report['all_slides_have_notes']
target = root / 'work/ppt_20261106/package_qa.json'
target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({key: report[key] for key in ['final_sha256', 'byte_count', 'all_source_hashes_match', 'shared_template_artwork_preserved', 'native_tables_verified', 'all_slides_have_notes']}, ensure_ascii=False))
