export function programs() {
    return {
        programList: [
            {
                id: 1,
                title: 'Beginner Boxing',
                icon: 'award',
                description: 'Perfect for those new to boxing. Learn fundamental techniques, footwork, and basic combinations in a supportive environment.',
                features: [
                    'Basic stance and footwork',
                    'Fundamental punches (jab, cross, hook, uppercut)',
                    'Defensive techniques',
                    'Conditioning drills',
                    '3 classes per week'
                ],
                price: '$99/month'
            },
            {
                id: 2,
                title: 'Advanced Training',
                icon: 'flame',
                description: 'Take your skills to the next level with advanced combinations, sparring sessions, and competition preparation.',
                features: [
                    'Advanced combinations',
                    'Sparring sessions',
                    'Fight strategy',
                    'Strength & conditioning',
                    'Unlimited classes',
                    'Competition prep'
                ],
                price: '$149/month'
            },
            {
                id: 3,
                title: 'Personal Training',
                icon: 'target',
                description: 'One-on-one coaching tailored to your specific goals. Get personalized attention and accelerated progress.',
                features: [
                    'Customized training plan',
                    'Individual attention',
                    'Flexible scheduling',
                    'Video analysis',
                    'Nutrition guidance',
                    'Goal tracking'
                ],
                price: '$299/month'
            }
        ]
    };
}
