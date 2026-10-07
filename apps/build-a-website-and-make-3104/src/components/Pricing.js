export function pricing() {
  return {
    plans: [
      { name: 'Solo', price: '$0', per: '/forever', tagline: 'For indie builders and side projects.',
        featured: false,
        features: ['1 workspace', 'Unlimited docs', 'GitHub sync', 'Community support'] },
      { name: 'Team', price: '$18', per: '/user / mo', tagline: 'Everything a shipping team needs.',
        featured: true,
        features: ['Unlimited workspaces', 'Auto release notes', 'SSO + SCIM', 'Ship metrics dashboard', 'Priority support'] },
      { name: 'Enterprise', price: 'Custom', per: '', tagline: 'For larger orgs with compliance needs.',
        featured: false,
        features: ['SOC 2 Type II report', 'Custom data residency', 'Dedicated CSM', 'Uptime SLA', 'Audit-log export'] },
    ],
  };
}
