"""Resolve explicitly bound module namespaces within one recipient dashboard."""
import unicodedata

def canonical_group(name, group, bindings):
    candidates=[value for value in (group,name) if isinstance(value,str)]
    for prefix,module in sorted(bindings,key=lambda row:len(row[0]),reverse=True):
        for value in candidates:
            normalized=unicodedata.normalize('NFKC',value).strip().casefold()
            if normalized==prefix or (normalized.startswith(prefix) and normalized[len(prefix):len(prefix)+1] in {' ','-','_','·','|',':'}):
                return module
    return group
