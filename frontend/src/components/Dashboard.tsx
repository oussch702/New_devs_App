import React, { useEffect, useState } from "react";
import { RevenueSummary } from "./RevenueSummary";
import { useAuth } from "../contexts/AuthContext.new";
import { SecureAPI, type DashboardProperty } from "../lib/secureApi";

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

const Dashboard: React.FC = () => {
  const { user } = useAuth();
  const identity = `${user?.id ?? ''}:${user?.tenant_id ?? ''}`;
  // Reset reporting state before displaying a different account's data.
  return <PropertyRevenueDashboard key={identity} />;
};

const PropertyRevenueDashboard: React.FC = () => {
  const [properties, setProperties] = useState<DashboardProperty[]>([]);
  const [selectedProperty, setSelectedProperty] = useState('');
  const [year, setYear] = useState('2024');
  const [month, setMonth] = useState('3');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const reportYear = Number(year);
  const validYear = /^\d{4}$/.test(year) && reportYear >= 1 && reportYear <= 9998;

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    SecureAPI.getDashboardProperties().then(result => {
      if (!active) return;
      setProperties(result.properties);
      setSelectedProperty(result.properties[0]?.id ?? '');
    }).catch(() => {
      if (active) setError('Unable to load your properties. Please try again.');
    }).finally(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [retry]);

  return (
    <div className="p-4 lg:p-6 min-h-full">
      <div className="max-w-7xl mx-auto">
        <h1 className="text-2xl font-bold mb-6 text-gray-900">Property Management Dashboard</h1>
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4 lg:p-6">
          <div className="mb-6">
            <div className="flex flex-col sm:flex-row sm:justify-between sm:items-start gap-4">
              <div>
                <h2 className="text-lg lg:text-xl font-medium text-gray-900 mb-2">Revenue Overview</h2>
                <p className="text-sm lg:text-base text-gray-600">Monthly and annual performance for your properties</p>
              </div>
              <div className="flex flex-wrap gap-3">
                <div className="flex flex-col">
                  <label htmlFor="revenue-property" className="text-xs font-medium text-gray-700 mb-1">Select Property</label>
                  <select id="revenue-property" value={selectedProperty} onChange={event => setSelectedProperty(event.target.value)}
                    disabled={loading || properties.length === 0}
                    className="w-full min-w-[200px] px-3 py-2 border border-gray-300 rounded-md text-sm">
                    {!properties.length && <option value="">{loading ? 'Loading properties…' : 'No properties'}</option>}
                    {properties.map(property => <option key={property.id} value={property.id}>{property.name}</option>)}
                  </select>
                </div>
                <div className="flex flex-col">
                  <label htmlFor="revenue-month" className="text-xs font-medium text-gray-700 mb-1">Period</label>
                  <select id="revenue-month" value={month} onChange={event => setMonth(event.target.value)}
                    className="px-3 py-2 border border-gray-300 rounded-md text-sm">
                    <option value="">Full year</option>
                    {MONTHS.map((name, index) => <option key={name} value={index + 1}>{name}</option>)}
                  </select>
                </div>
                <div className="flex flex-col">
                  <label htmlFor="revenue-year" className="text-xs font-medium text-gray-700 mb-1">Year</label>
                  <input id="revenue-year" type="number" min="1" max="9998" value={year}
                    onChange={event => setYear(event.target.value)} aria-invalid={!validYear}
                    className="w-24 px-3 py-2 border border-gray-300 rounded-md text-sm" />
                </div>
              </div>
            </div>
          </div>
          {loading ? <p role="status" className="text-gray-600">Loading your properties…</p> : error ? (
            <div role="alert" className="p-4 text-red-700 bg-red-50 rounded-lg">
              {error} <button className="underline" onClick={() => setRetry(value => value + 1)}>Retry</button>
            </div>
          ) : !properties.length ? <p className="text-gray-600">No properties are assigned to your organization.</p> : !validYear ? (
            <p role="alert" className="text-red-700">Enter a four-digit year between 0001 and 9998.</p>
          ) : selectedProperty ? (
            <RevenueSummary key={`${selectedProperty}:${year}:${month}`} propertyId={selectedProperty} year={reportYear} month={month ? Number(month) : undefined} />
          ) : null}
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
