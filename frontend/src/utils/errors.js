export function formatApiError(detail, fallback = 'No se pudo completar la operación') {
  if (typeof detail === 'string' && detail.trim()) return detail;

  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      if (typeof item === 'string') return item;
      if (!item || typeof item !== 'object') return '';

      const message = typeof item.msg === 'string' ? item.msg : '';
      const location = Array.isArray(item.loc)
        ? item.loc.filter((part) => part !== 'body').join(' → ')
        : '';
      if (message && location) return `${location}: ${message}`;
      if (message) return message;
      return formatApiError(item.detail ?? item.message, '');
    }).filter(Boolean);

    if (messages.length) return messages.join('\n');
  }

  if (detail && typeof detail === 'object') {
    const nestedDetail = formatApiError(detail.detail, '');
    if (nestedDetail) return nestedDetail;
    const nestedMessage = formatApiError(detail.message, '');
    if (nestedMessage) return nestedMessage;
    const responseDetail = formatApiError(detail.response?.data?.detail, '');
    if (responseDetail) return responseDetail;
  }

  return fallback;
}
