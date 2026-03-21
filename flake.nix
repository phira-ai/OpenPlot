{
  description = "OpenPlot: visual plot debugger";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
      ];
    in
    flake-utils.lib.eachSystem systems (
      system:
      let
        pkgs = import nixpkgs { inherit system; };
        lib = pkgs.lib;

        basePythonPackages =
          ps: with ps; [
            click
            fastapi
            matplotlib
            mcp
            numpy
            openpyxl
            pandas
            pydantic
            seaborn
            uvicorn
            websockets
          ];

        desktopPythonPackages =
          ps:
          basePythonPackages ps
          ++ [
            ps.pywebview
          ]
          ++ lib.optionals pkgs.stdenv.hostPlatform.isLinux [
            ps.pyqt6
            ps."pyqt6-webengine"
            ps.qtpy
          ]
          ++ lib.optionals pkgs.stdenv.hostPlatform.isDarwin [
            ps."pyobjc-core"
            ps."pyobjc-framework-Cocoa"
            ps."pyobjc-framework-Quartz"
            ps."pyobjc-framework-Security"
            ps."pyobjc-framework-WebKit"
          ];

        installOpenPlotSource = ''
          mkdir -p $out/lib/openplot
          cp -r src $out/lib/openplot/
          cp pyproject.toml README.md $out/lib/openplot/

          mkdir -p $out/lib/openplot/src/openplot/static
          cp -r ${frontendDist}/dist/. $out/lib/openplot/src/openplot/static/
        '';

        frontendDist = pkgs.buildNpmPackage {
          pname = "openplot-frontend";
          version = "1.1.0";
          src = ./frontend;
          npmDepsHash = "sha256-tx8lsrlYHVpLYugjiDVTO+fWwTC1e6DAEzBrtQi7O0I=";
          npmBuildScript = "build";

          installPhase = ''
            runHook preInstall
            mkdir -p $out/dist
            cp -r ../src/openplot/static/. $out/dist/
            runHook postInstall
          '';
        };

        runtimePython = pkgs.python312.withPackages (ps: basePythonPackages ps);

        desktopPython = pkgs.python312.withPackages (ps: desktopPythonPackages ps);

        openplot = pkgs.stdenvNoCC.mkDerivation {
          pname = "openplot";
          version = "1.1.0";
          src = lib.cleanSource ./.;
          nativeBuildInputs = [ pkgs.makeWrapper ];

          installPhase = ''
            runHook preInstall

            ${installOpenPlotSource}

            mkdir -p $out/bin
            makeWrapper ${runtimePython}/bin/python $out/bin/openplot \
              --add-flags "-m openplot.cli" \
              --set PYTHONPATH "$out/lib/openplot/src"

            runHook postInstall
          '';

          meta = {
            description = "Visual plot debugger for LLM-generated plotting scripts";
            mainProgram = "openplot";
            platforms = lib.platforms.linux ++ lib.platforms.darwin;
          };
        };

        openplotDesktop = pkgs.stdenvNoCC.mkDerivation {
          pname = "openplot-desktop";
          version = "1.1.0";
          src = lib.cleanSource ./.;
          nativeBuildInputs = [
            pkgs.makeWrapper
          ]
          ++ lib.optionals pkgs.stdenv.hostPlatform.isLinux [ pkgs.qt6.wrapQtAppsHook ];
          buildInputs = lib.optionals pkgs.stdenv.hostPlatform.isLinux [
            pkgs.qt6.qtbase
            pkgs.qt6.qtwayland
            pkgs.qt6.qtwebengine
          ];

          installPhase = ''
            runHook preInstall

            ${installOpenPlotSource}

            mkdir -p $out/bin
            makeWrapper ${desktopPython}/bin/python $out/bin/openplot-desktop \
              --add-flags "-m openplot.desktop" \
              --set PYTHONPATH "$out/lib/openplot/src"

            mkdir -p $out/share/applications
            install -Dm644 packaging/linux/openplot.desktop $out/share/applications/openplot-desktop.desktop

            mkdir -p $out/share/icons/hicolor/512x512/apps
            install -Dm644 packaging/macos/openplot.iconset/icon_512x512.png $out/share/icons/hicolor/512x512/apps/openplot.png

            runHook postInstall
          '';

          meta = {
            description = "Desktop launcher for the OpenPlot visual plot debugger";
            mainProgram = "openplot-desktop";
            platforms = lib.platforms.linux ++ lib.platforms.darwin;
          };
        };
      in
      {
        packages = {
          inherit openplot;
          "openplot-desktop" = openplotDesktop;
          default = openplot;
        };

        apps = {
          openplot = {
            type = "app";
            program = "${openplot}/bin/openplot";
          };
          default = {
            type = "app";
            program = "${openplot}/bin/openplot";
          };
          "openplot-desktop" = {
            type = "app";
            program = "${openplotDesktop}/bin/openplot-desktop";
          };
        };
      }
    )
    // {
      overlays.default = final: _prev: {
        openplot = self.packages.${final.system}.openplot;
        "openplot-desktop" = self.packages.${final.system}."openplot-desktop";
      };
    };
}
