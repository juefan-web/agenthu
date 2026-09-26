declare module "sm-crypto" {
  export const sm2: { doEncrypt(value: string, publicKey: string): string };
}
