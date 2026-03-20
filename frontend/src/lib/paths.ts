function firstMnemonic(segment: string): string {
  const trimmed = segment.trim();
  if (!trimmed) {
    return "";
  }

  const alnum = trimmed.match(/[A-Za-z0-9]/);
  return alnum ? alnum[0].toLowerCase() : trimmed[0].toLowerCase();
}

function middleEllipsis(text: string, maxLength: number): string {
  if (maxLength < 5 || text.length <= maxLength) {
    return text;
  }
  const keep = maxLength - 3;
  const left = Math.ceil(keep / 2);
  const right = Math.floor(keep / 2);
  return `${text.slice(0, left)}...${text.slice(text.length - right)}`;
}

export function directoryPrefix(pathLike: string): string {
  const normalized = pathLike.trim().replace(/\\/g, "/");
  if (!normalized) {
    return "";
  }
  if (normalized.endsWith("/")) {
    return normalized;
  }
  const slashIndex = normalized.lastIndexOf("/");
  if (slashIndex === -1) {
    return "";
  }
  return normalized.slice(0, slashIndex + 1);
}

export function compactPathDisplay(pathLike: string, maxLength = 64): string {
  const normalized = pathLike.trim().replace(/\\/g, "/");
  if (!normalized || normalized.length <= maxLength) {
    return normalized;
  }

  let prefix = "";
  let remainder = normalized;

  if (normalized.startsWith("~/")) {
    prefix = "~/";
    remainder = normalized.slice(2);
  } else if (/^[A-Za-z]:\//.test(normalized)) {
    prefix = normalized.slice(0, 3);
    remainder = normalized.slice(3);
  } else if (normalized.startsWith("/")) {
    prefix = "/";
    remainder = normalized.slice(1);
  }

  const parts = remainder.split("/").filter(Boolean);
  if (parts.length <= 1) {
    return middleEllipsis(normalized, maxLength);
  }

  const build = (tailCount: number) => {
    const tail = parts.slice(-tailCount);
    const hidden = parts.slice(0, Math.max(0, parts.length - tailCount));
    const mnemonics = hidden.map(firstMnemonic).filter(Boolean).join("/");
    const tailPart = tail.join("/");
    if (mnemonics) {
      return `${prefix}${mnemonics}/.../${tailPart}`;
    }
    return `${prefix}.../${tailPart}`;
  };

  const withTwoTail = build(2);
  if (withTwoTail.length <= maxLength) {
    return withTwoTail;
  }

  const withOneTail = build(1);
  if (withOneTail.length <= maxLength) {
    return withOneTail;
  }

  const fileName = parts[parts.length - 1] || normalized;
  const compactFile = middleEllipsis(fileName, Math.max(12, maxLength - prefix.length - 7));
  return `${prefix}.../${compactFile}`;
}
