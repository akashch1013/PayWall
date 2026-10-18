export const CATEGORIES = [
  { value: 'tops', label: 'Tops', icon: '👕' },
  { value: 'bottoms', label: 'Bottoms', icon: '👖' },
  { value: 'dresses', label: 'Dresses', icon: '👗' },
  { value: 'jackets', label: 'Jackets', icon: '🧥' },
  { value: 'shoes', label: 'Shoes', icon: '👟' },
  { value: 'accessories', label: 'Accessories', icon: '👜' },
  { value: 'other', label: 'Other', icon: '🛍️' },
];

export const CONDITIONS = [
  { value: 'new', label: 'New with tags' },
  { value: 'like_new', label: 'Like new' },
  { value: 'good', label: 'Good' },
  { value: 'fair', label: 'Fair' },
];

export const SORTS = [
  { value: 'newest', label: 'Newest first' },
  { value: 'price_asc', label: 'Price: low to high' },
  { value: 'price_desc', label: 'Price: high to low' },
];

export const MAX_PRICE = 1_000_000;
export const MAX_UPLOAD_BYTES = 5 * 1024 * 1024;
export const IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/gif'];

const byValue = (list) => Object.fromEntries(list.map((x) => [x.value, x]));
const categoryMap = byValue(CATEGORIES);
const conditionMap = byValue(CONDITIONS);

export const categoryLabel = (v) => categoryMap[v]?.label ?? v;
export const categoryIcon = (v) => categoryMap[v]?.icon ?? '🛍️';
export const conditionLabel = (v) => conditionMap[v]?.label ?? v;
export const formatPrice = (n) => `₹${Number(n).toLocaleString('en-IN')}`;
export const formatDate = (iso) =>
  new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
