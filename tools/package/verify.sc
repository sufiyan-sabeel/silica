use fs

use json

use string

const FACTS: String = "build/packaging/facts.json"

const REPORT: String = "build/packaging/report.json"

const PYPROJECT: String = "pyproject.toml"

const VERSION_MODULE: String = "silica/__init__.py"

const CLI: String = "silica/cli.py"

const INSTALLER: String = "install.sh"

const CHANGELOG: String = "CHANGELOG.md"

const SUMS: String = "dist/SHA256SUMS.txt"

sfn fail(failures: List, message: String) {
    push(failures, message)
}

sfn need(failures: List, path: String, needle: String, what: String) {
    si fs.exists(path) == nein {
        fail(failures, what + ": " + path + " does not exist")
        ret
    }
    let text: String = fs.read_text(path)
    si string.contains(text, needle) == nein {
        fail(failures, what + ": " + path + " does not contain " + needle)
    }
}

sfn contains(list: List, value: String) -> Bool {
    per item in list {
        si item == value {
            ret oui
        }
    }
    ret nein
}

sfn starts_with_any(value: String, prefixes: List) -> String {
    per prefix in prefixes {
        si string.starts_with(value, prefix) {
            ret prefix
        }
    }
    ret ""
}

sfn any_ends_with(files: List, suffix: String) -> Bool {
    per entry in files {
        si string.ends_with(entry, suffix) {
            ret oui
        }
    }
    ret nein
}

sfn digest_of(text: String, name: String) -> String {
    per line in string.split(text, "\n") {
        let parts: List = string.split(string.trim(line), " ")
        si len(parts) >= 2 {
            si parts[len(parts) - 1] == name {
                ret parts[0]
            }
        }
    }
    ret ""
}

sfn check_versions(failures: List, version: String) {
    need(failures, PYPROJECT, "version = \"" + version + "\"", "version in pyproject")
    need(failures, PYPROJECT, "name = \"silica-lang\"", "distribution name")
    need(failures, PYPROJECT, "silica = \"silica.cli:main\"", "entry point")
    need(failures, VERSION_MODULE, "__version__ = \"" + version + "\"", "version in the package")
    need(failures, CLI, "VERSION = \"" + version + "\"", "version in the CLI")
    need(failures, INSTALLER, "SILICA_VERSION:-" + version, "version in the installer")
    need(failures, CHANGELOG, "## [" + version + "]", "version in the changelog")
}

sfn check_wheel(failures: List, wheel: Any, required: List, forbidden: List) {
    let files: List = wheel["files"]
    per needed in required {
        si contains(files, needed) == nein {
            fail(failures, "wheel is missing " + needed)
        }
    }
    per entry in files {
        let prefix: String = starts_with_any(entry, forbidden)
        si prefix != "" {
            fail(failures, "wheel carries source-only file " + entry)
        }
    }
    let metadata: Bool = nein
    let entry_points: Bool = nein
    per entry in files {
        si string.ends_with(entry, ".dist-info/METADATA") {
            metadata = oui
        }
        si string.ends_with(entry, ".dist-info/entry_points.txt") {
            entry_points = oui
        }
    }
    si metadata == nein {
        fail(failures, "wheel has no dist-info/METADATA")
    }
    si entry_points == nein {
        fail(failures, "wheel has no dist-info/entry_points.txt, so no silica command")
    }
}

sfn check_sdist(failures: List, sdist: Any, suffixes: List) {
    let files: List = sdist["files"]
    per needed in suffixes {
        si any_ends_with(files, needed) == nein {
            fail(failures, "sdist is missing " + needed)
        }
    }
}

sfn check_names(failures: List, version: String, wheel: Any, sdist: Any) {
    si string.contains(wheel["name"], "silica_lang-" + version) == nein {
        fail(failures, "wheel name does not carry the version: " + wheel["name"])
    }
    si string.contains(sdist["name"], "silica_lang-" + version) == nein {
        fail(failures, "sdist name does not carry the version: " + sdist["name"])
    }
}

sfn check_sums(failures: List, wheel: Any, sdist: Any) {
    si fs.exists(SUMS) == nein {
        fail(failures, "no SHA256SUMS.txt next to the artefacts; run tools/package/sums.sc")
        ret
    }
    let text: String = fs.read_text(SUMS)
    let wheel_name: String = wheel["name"]
    let sdist_name: String = sdist["name"]
    let wheel_sum: String = digest_of(text, wheel_name)
    let sdist_sum: String = digest_of(text, sdist_name)
    si wheel_sum == "" {
        fail(failures, "SHA256SUMS.txt does not list " + wheel_name)
    } sino {
        si wheel_sum != wheel["sha256"] {
            fail(failures, "checksum mismatch for " + wheel_name)
        }
    }
    si sdist_sum == "" {
        fail(failures, "SHA256SUMS.txt does not list " + sdist_name)
    } sino {
        si sdist_sum != sdist["sha256"] {
            fail(failures, "checksum mismatch for " + sdist_name)
        }
    }
}

sfn main() {
    si fs.exists(FACTS) == nein {
        sprint("packaging check: " + FACTS + " not found")
        sprint("run tools/package/facts.py first; it writes the facts this checks")
        halt(1)
    }
    let facts: Any = json.parse(fs.read_text(FACTS))
    let version: String = facts["version"]
    let wheel: Any = facts["wheel"]
    let sdist: Any = facts["sdist"]
    let failures: List = []
    check_versions(failures, version)
    check_names(failures, version, wheel, sdist)
    check_wheel(failures, wheel, facts["required_wheel"], facts["forbidden_wheel_prefixes"])
    check_sdist(failures, sdist, facts["required_sdist_suffixes"])
    check_sums(failures, wheel, sdist)
    sprint("Silica packaging check for " + facts["distribution"] + " " + version)
    sprint("  wheel " + wheel["name"] + " (" + str(len(wheel["files"])) + " files)")
    sprint("  sdist " + sdist["name"] + " (" + str(len(sdist["files"])) + " files)")
    si len(failures) == 0 {
        sprint("  all checks passed")
    } sino {
        sprint("  " + str(len(failures)) + " problem(s):")
        per problem in failures {
            sprint("    - " + problem)
        }
    }
    let report: Map = {"distribution": facts["distribution"], "version": version, "ok": len(failures) == 0, "problems": failures, "wheel": wheel["name"], "wheel_sha256": wheel["sha256"], "sdist": sdist["name"], "sdist_sha256": sdist["sha256"]}
    fs.write_text(REPORT, json.stringify(report, 2))
    si len(failures) > 0 {
        halt(1)
    }
}
