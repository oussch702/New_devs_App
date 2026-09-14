import React, { useEffect, useState } from 'react';
import { SecureAPI, type DashboardSummary } from '../lib/secureApi';
import { formatRevenueAmount } from '../utils/revenue';

interface RevenueSummaryProps {
    propertyId: string;
    year: number;
    month?: number;
}

export const RevenueSummary: React.FC<RevenueSummaryProps> = ({ propertyId, year, month }) => {
    const [data, setData] = useState<DashboardSummary | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [retry, setRetry] = useState(0);

    useEffect(() => {
        let active = true;
        setLoading(true);
        setData(null);
        setError('');
        SecureAPI.getDashboardSummary(propertyId, { year, month }).then(response => {
            // Cleanup ignores late responses from earlier selections and sessions.
            if (active) setData(response);
        }).catch(err => {
            if (active) setError(err instanceof Error ? err.message : 'Failed to load revenue data');
        }).finally(() => {
            if (active) setLoading(false);
        });
        return () => { active = false; };
    }, [propertyId, year, month, retry]);

    if (loading) return (
        <div role="status" aria-label="Loading revenue" className="bg-white p-6 rounded-xl shadow-sm border border-gray-200">
            <div className="animate-pulse space-y-4">
                <div className="h-4 bg-gray-100 rounded w-1/4" />
                <div className="h-8 bg-gray-100 rounded w-1/2" />
                <div className="flex gap-4 pt-4"><div className="h-12 bg-gray-100 rounded flex-1" /><div className="h-12 bg-gray-100 rounded flex-1" /></div>
            </div>
        </div>
    );
    if (error) return (
        <div role="alert" className="p-4 text-red-700 bg-red-50 rounded-lg">
            {error} <button className="underline" onClick={() => setRetry(value => value + 1)}>Retry</button>
        </div>
    );
    if (!data) return null;

    const period = data.month && data.year
        ? `${new Intl.DateTimeFormat('en', { month: 'long', timeZone: 'UTC' }).format(new Date(Date.UTC(2000, data.month - 1, 1)))} ${data.year}`
        : data.year ? `Full year ${data.year}` : 'All time';

    return (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
            <div className="p-6">
                <div className="mb-6">
                    <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wide">Total Revenue</h2>
                    <p className="text-sm text-gray-600 mt-1">{period} · {data.timezone}</p>
                    <div className="space-y-2 mt-3">
                        {data.totals_by_currency.map(total => (
                            <div key={total.currency} className="text-3xl font-bold text-gray-900 tracking-tight">
                                {total.currency} {formatRevenueAmount(total.total_revenue)}
                            </div>
                        ))}
                    </div>
                    {data.totals_by_currency.length > 1 && <p className="text-sm text-gray-600 mt-2">Currencies are reported separately.</p>}
                </div>
                <div className="grid grid-cols-2 gap-4 pt-4 border-t border-gray-100">
                    <div>
                        <p className="text-xs text-gray-500 font-medium uppercase tracking-wider">Property ID</p>
                        <p className="text-sm font-semibold text-gray-700 font-mono mt-1">{data.property_id}</p>
                    </div>
                    <div>
                        <p className="text-xs text-gray-500 font-medium uppercase tracking-wider">Reservations</p>
                        <p className="text-sm font-semibold text-gray-700 mt-1">{data.reservations_count} <span className="font-normal text-gray-400">bookings</span></p>
                    </div>
                </div>
                <p className="mt-4 text-xs text-gray-500">Revenue is assigned to the check-in date in the property’s time zone.</p>
            </div>
        </div>
    );
};
