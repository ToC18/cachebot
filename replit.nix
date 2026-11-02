{ pkgs }: {
  deps = [
    pkgs.python312Full
    pkgs.postgresql
    pkgs.stdenv.cc.cc.lib
  ];
  env = {
    LD_LIBRARY_PATH = "${pkgs.stdenv.cc.cc.lib}/lib";
  };
}
