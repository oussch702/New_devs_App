/** Format the server's rounded decimal string without a floating-point conversion. */
export function formatRevenueAmount(amount: string): string {
  if (!/^-?\d+\.\d{2}$/.test(amount)) throw new Error('Invalid revenue amount');
  const [whole, cents] = amount.split('.');
  return `${whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}.${cents}`;
}
