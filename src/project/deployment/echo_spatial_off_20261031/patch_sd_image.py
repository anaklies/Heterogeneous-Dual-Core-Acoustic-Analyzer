"""Patch image.ub for the 20261031 device-side spatial-interface shutdown.

Source: deployment/echo_stipa_8s_progress_20261030/image.ub (sha256 cba07779...),
the image.ub currently on the board SD card. The ONLY change is the ramdisk cpio
entry opt/echo/registry/INTERFACE_REGISTRY.json, replaced by the canonical
45-feature registry in registry/INTERFACE_REGISTRY.json. Kernel, device tree,
FIT metadata and all other ramdisk entries stay byte-identical (proven below).
"""
from pathlib import Path
import json

from image_patch_lib import (TARGET_ENTRY, build_patched_image, sha, verify_patch)

R = Path(__file__).resolve().parent
PROJECT = R.parents[1]
SOURCE = PROJECT / 'deployment/echo_stipa_8s_progress_20261030/image.ub'
SOURCE_SHA = 'cba07779ad32643380a96462569dabb4f4f4b2ec62bc9476a8dd4caa1fbc4902'
OLD_REGISTRY_SHA = '301636354dc1902426fe57e4dbd1a0a95809323d0ad2eff46cd71cad51a5bead'
NEW_REGISTRY = R / 'registry/INTERFACE_REGISTRY.json'
NEW_REGISTRY_SHA = 'dcbc393723513773867f6a9d96f396eb22b13386060881fdae06dda4ecb77628'
OUT = R / 'image.ub'


def main():
    source = SOURCE.read_bytes()
    new_registry = NEW_REGISTRY.read_bytes()
    if sha(new_registry) != NEW_REGISTRY_SHA:
        raise SystemExit('registry/INTERFACE_REGISTRY.json is not the canonical 45-feature copy')
    output, build = build_patched_image(source, new_registry, SOURCE_SHA, OLD_REGISTRY_SHA)
    result = verify_patch(source, output, new_registry,
                          expected_source_sha=SOURCE_SHA,
                          expected_output_sha=sha(output),
                          expected_old_registry_sha=OLD_REGISTRY_SHA,
                          expected_new_registry_sha=NEW_REGISTRY_SHA)
    if result['status'] != 'PASS':
        raise SystemExit('offline patch verification failed: ' + json.dumps(result['summary']))
    OUT.write_bytes(output)
    summary = result['summary']
    report = {
        'source': 'deployment/echo_stipa_8s_progress_20261030/image.ub',
        'sourceSHA256': build['sourceSHA256'],
        'sourceBytes': build['sourceBytes'],
        'image': 'image.ub',
        'imageSHA256': build['imageSHA256'],
        'bytes': build['bytes'],
        'changedRamdiskEntries': [TARGET_ENTRY],
        'changedEntryCount': 1,
        'ramdiskEntries': build['ramdiskEntries'],
        'unchangedRamdiskEntries': build['ramdiskEntries'] - 1,
        'oldRegistrySHA256': build['oldRegistrySHA256'],
        'oldRegistryBytes': build['oldRegistryBytes'],
        'newRegistrySHA256': build['newRegistrySHA256'],
        'newRegistryBytes': build['newRegistryBytes'],
        'kernelSHA256': build['kernelSHA256'],
        'dtbSHA256': build['dtbSHA256'],
        'kernelAndDTBUnchanged': True,
        'kernelAndDTBByteIdentical': True,
        'gatewayChanged': False,
        'bitstreamChanged': False,
        'bootChanged': False,
        'ramdiskCompressedBytes': {'source': build['sourceRamdiskCompressedBytes'],
                                   'output': build['outputRamdiskCompressedBytes']},
        'fdtHeaderChangedFields': summary['fdtHeaderChangedFields'],
        'byteIdenticalOutsidePatch': True,
        'proof': summary['proof'],
        'verification': {'status': result['status'], 'checks': len(result['checks']),
                         'report': 'VERIFY.json'},
    }
    (R / 'SD_PATCH.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
