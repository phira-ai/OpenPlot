import type { IconifyIcon } from "@iconify/types";
import defaultFileIcon from "@iconify-icons/vscode-icons/default-file";
import fileTypeBinaryIcon from "@iconify-icons/vscode-icons/file-type-binary";
import fileTypeConfigIcon from "@iconify-icons/vscode-icons/file-type-config";
import fileTypeDbIcon from "@iconify-icons/vscode-icons/file-type-db";
import fileTypeExcelIcon from "@iconify-icons/vscode-icons/file-type-excel";
import fileTypeImageIcon from "@iconify-icons/vscode-icons/file-type-image";
import fileTypeIniIcon from "@iconify-icons/vscode-icons/file-type-ini";
import fileTypeJsonIcon from "@iconify-icons/vscode-icons/file-type-json";
import fileTypeJupyterIcon from "@iconify-icons/vscode-icons/file-type-jupyter";
import fileTypeMarkdownIcon from "@iconify-icons/vscode-icons/file-type-markdown";
import fileTypePdfIcon from "@iconify-icons/vscode-icons/file-type-pdf2";
import fileTypePythonIcon from "@iconify-icons/vscode-icons/file-type-python";
import fileTypeShellIcon from "@iconify-icons/vscode-icons/file-type-shell";
import fileTypeSqlIcon from "@iconify-icons/vscode-icons/file-type-sql";
import fileTypeSvgIcon from "@iconify-icons/vscode-icons/file-type-svg";
import fileTypeTextIcon from "@iconify-icons/vscode-icons/file-type-text";
import fileTypeTomlIcon from "@iconify-icons/vscode-icons/file-type-toml";
import fileTypeXmlIcon from "@iconify-icons/vscode-icons/file-type-xml";
import fileTypeYamlIcon from "@iconify-icons/vscode-icons/file-type-yaml";
import fileTypeZipIcon from "@iconify-icons/vscode-icons/file-type-zip";

const EXTENSION_ICON_MAP: Record<string, IconifyIcon> = {
  py: fileTypePythonIcon,
  ipynb: fileTypeJupyterIcon,
  csv: fileTypeExcelIcon,
  tsv: fileTypeExcelIcon,
  xls: fileTypeExcelIcon,
  xlsx: fileTypeExcelIcon,
  parquet: fileTypeDbIcon,
  feather: fileTypeDbIcon,
  arrow: fileTypeDbIcon,
  db: fileTypeDbIcon,
  sqlite: fileTypeDbIcon,
  sql: fileTypeSqlIcon,
  json: fileTypeJsonIcon,
  jsonl: fileTypeJsonIcon,
  json5: fileTypeJsonIcon,
  yaml: fileTypeYamlIcon,
  yml: fileTypeYamlIcon,
  toml: fileTypeTomlIcon,
  ini: fileTypeIniIcon,
  env: fileTypeConfigIcon,
  conf: fileTypeConfigIcon,
  cfg: fileTypeConfigIcon,
  txt: fileTypeTextIcon,
  md: fileTypeMarkdownIcon,
  markdown: fileTypeMarkdownIcon,
  xml: fileTypeXmlIcon,
  svg: fileTypeSvgIcon,
  png: fileTypeImageIcon,
  jpg: fileTypeImageIcon,
  jpeg: fileTypeImageIcon,
  gif: fileTypeImageIcon,
  webp: fileTypeImageIcon,
  bmp: fileTypeImageIcon,
  tif: fileTypeImageIcon,
  tiff: fileTypeImageIcon,
  pdf: fileTypePdfIcon,
  zip: fileTypeZipIcon,
  gz: fileTypeZipIcon,
  bz2: fileTypeZipIcon,
  xz: fileTypeZipIcon,
  tar: fileTypeZipIcon,
  sh: fileTypeShellIcon,
  bash: fileTypeShellIcon,
  zsh: fileTypeShellIcon,
  fish: fileTypeShellIcon,
  ps1: fileTypeShellIcon,
  npy: fileTypeBinaryIcon,
  npz: fileTypeBinaryIcon,
  h5: fileTypeBinaryIcon,
  hdf5: fileTypeBinaryIcon,
  pkl: fileTypeBinaryIcon,
  joblib: fileTypeBinaryIcon,
};

function fileExtension(pathLike: string): string {
  const normalized = pathLike.trim().replace(/\\/g, "/");
  const baseName = normalized.split("/").at(-1) ?? "";
  if (!baseName) {
    return "";
  }

  if (baseName.startsWith(".") && !baseName.slice(1).includes(".")) {
    return baseName.slice(1).toLowerCase();
  }

  const dotIndex = baseName.lastIndexOf(".");
  if (dotIndex <= 0 || dotIndex >= baseName.length - 1) {
    return "";
  }

  return baseName.slice(dotIndex + 1).toLowerCase();
}

export function iconForPath(pathLike: string): IconifyIcon {
  const extension = fileExtension(pathLike);
  if (!extension) {
    return defaultFileIcon;
  }
  return EXTENSION_ICON_MAP[extension] ?? defaultFileIcon;
}

export function summarizeSelectedFiles(paths: string[]): string {
  if (paths.length === 0) {
    return "No sources yet";
  }

  const names = paths.map((path) => path.split(/[\\/]/).at(-1) || path);
  if (names.length === 1) {
    return names[0];
  }
  if (names.length === 2) {
    return `${names[0]}, ${names[1]}`;
  }
  return `${names[0]}, ${names[1]} +${names.length - 2}`;
}
