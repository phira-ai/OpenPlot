nix shell \
  nixpkgs#bash \
  nixpkgs#python3 \
  nixpkgs#file \
  nixpkgs#curl \
  nixpkgs#alsa-lib \
  nixpkgs#libglvnd \
  nixpkgs#libgbm \
  nixpkgs#libxkbcommon \
  nixpkgs#libxshmfence \
  nixpkgs#libxcomposite \
  nixpkgs#libxext \
  nixpkgs#libxrender \
  nixpkgs#libxtst \
  nixpkgs#libxcb-keysyms \
  nixpkgs#xkeyboard-config \
  -c bash -lc '
    export OPENPLOT_LIB_SEARCH_PATHS="$(
      nix path-info \
        nixpkgs#alsa-lib \
        nixpkgs#libglvnd \
        nixpkgs#libgbm \
        nixpkgs#libxkbcommon \
        nixpkgs#libxshmfence \
        nixpkgs#libxcomposite \
        nixpkgs#libxext \
        nixpkgs#libxrender \
        nixpkgs#libxtst \
        nixpkgs#libxcb-keysyms \
      | python -c "import sys; print(\":\".join(p.strip()+\"/lib\" for p in sys.stdin if p.strip()))"
    )"
    export OPENPLOT_XKB_CONFIG_ROOT="$(nix path-info nixpkgs#xkeyboard-config)/share/X11/xkb"
    bash packaging/linux/build_appimage.sh
  '
